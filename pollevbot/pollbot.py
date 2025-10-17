import requests
import logging
import time
from typing import Optional, Dict
from .endpoints import endpoints

logger = logging.getLogger(__name__)
__all__ = ['PollBot']


class LoginError(RuntimeError):
    """Error indicating that login failed."""


class PollBot:
    """Bot for answering polls on PollEverywhere.
    Responses are randomly selected.

    Usage:
    >>> bot = PollBot(user='username', password='password',
    ...               host='host', login_type='uw')
    >>> bot.run()

    Can also be used as a context manager.
    """

    def __init__(self, user: str, password: str, host: str,
                 login_type: str = 'uw', min_option: int = 0,
                 max_option: int = None, closed_wait: float = 5,
                 open_wait: float = 5, lifetime: float = float('inf'),
                 session_cookies: Optional[Dict[str, str]] = None,
                 firehose_token: Optional[str] = None):
        """
        Constructor. Creates a PollBot that answers polls on pollev.com.

        :param user: PollEv account username.
        :param password: PollEv account password.
        :param host: PollEv host name, i.e. 'uwpsych'
        :param login_type: Login protocol to use (either 'uw' or 'pollev').
                        If 'uw', uses MyUW (SAML2 SSO) to authenticate.
                        If 'pollev', uses pollev.com.
        :param min_option: Minimum index (0-indexed) of option to select (inclusive).
        :param max_option: Maximum index (0-indexed) of option to select (exclusive).
        :param closed_wait: Time to wait in seconds if no polls are open
                        before checking again.
        :param open_wait: Time to wait in seconds if a poll is open
                        before answering.
        :param lifetime: Lifetime of this PollBot (in seconds).
                        If float('inf'), runs forever.
        :param session_cookies: Optional mapping of cookie name to value used to
                        authenticate without performing a login.
        :param firehose_token: Optional AWS firehose token to poll for activity.
        :raises ValueError: if login_type is not 'uw' or 'pollev'.
        """
        if login_type not in {'uw', 'pollev'}:
            raise ValueError(f"'{login_type}' is not a supported login type. "
                             f"Use 'uw' or 'pollev'.")
        if login_type == 'pollev' and user.strip().lower().endswith('@uw.edu'):
            logger.warning(f"{user} looks like a UW email. "
                           f"Use login_type='uw' to log in with MyUW.")

        self.user = user
        self.password = password
        self.host = host
        self.login_type = login_type
        # 0-indexed minimum and maximum option
        # indices to select on poll.
        self.min_option = min_option
        self.max_option = max_option
        # Wait time in seconds if poll is
        # closed or open, respectively
        self.closed_wait = closed_wait
        self.open_wait = open_wait

        self.lifetime = lifetime
        self.start_time = time.time()
        self.session_cookies = session_cookies or {}
        self.firehose_token = firehose_token
        self.last_message_sequence = 0

        self.session = requests.Session()
        self.session.headers = {
            'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/70.0.3538.102 Safari/537.36"
        }

    def _update_last_message_sequence(self, sequence) -> None:
        """Track the latest firehose message sequence observed."""
        if sequence is None:
            return
        try:
            seq_int = int(sequence)
        except (TypeError, ValueError):
            logger.debug("firehose sequence value not an int; value=%s", sequence)
            return
        if seq_int > self.last_message_sequence:
            self.last_message_sequence = seq_int

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.session.close()

    @staticmethod
    def timestamp() -> float:
        return round(time.time() * 1000)

    def _get_csrf_token(self) -> str:
        url = endpoints['csrf'].format(timestamp=self.timestamp())
        return self.session.get(url).json()['token']

    def _pollev_login(self) -> bool:
        """
        Logs into PollEv through pollev.com.
        Returns True on success, False otherwise.
        """
        logger.info("Logging into PollEv through pollev.com.")

        r = self.session.post(endpoints['login'],
                              headers={'x-csrf-token': self._get_csrf_token()},
                              data={'login': self.user, 'password': self.password})
        # If login is successful, PollEv sends an empty HTTP response.
        return not r.text

    def _uw_login(self):
        """
        Logs into PollEv through MyUW.
        Returns True on success, False otherwise.
        """
        import bs4 as bs
        import re

        logger.info("Logging into PollEv through MyUW.")

        r = self.session.get(endpoints['uw_saml'])
        soup = bs.BeautifulSoup(r.text, "html.parser")
        data = soup.find('form', id='idplogindiv')['action']
        session_id = re.findall(r'jsessionid=(.*)\.', data)

        r = self.session.post(endpoints['uw_login'].format(id=session_id),
                              data={
                                  'j_username': self.user,
                                  'j_password': self.password,
                                  '_eventId_proceed': 'Sign in'
                              })
        soup = bs.BeautifulSoup(r.text, "html.parser")
        saml_response = soup.find('input', type='hidden')

        # When user authentication fails, UW will send an empty SAML response.
        if not saml_response:
            return False

        r = self.session.post(endpoints['uw_callback'],
                              data={'SAMLResponse': saml_response['value']})
        auth_tokens = re.findall('pe_auth_token=(.*)', r.url)
        if not auth_tokens:
            logger.error("MyUW login returned without an auth token. "
                         "Check your credentials or login_type.")
            return False
        auth_token = auth_tokens[0]
        self.session.post(endpoints['uw_auth_token'],
                          headers={'x-csrf-token': self._get_csrf_token()},
                          data={'token': auth_token})
        return True

    def login(self):
        """
        Logs into PollEv.

        :raises LoginError: if login failed.
        """
        if self.login_type.lower() == 'uw':
            success = self._uw_login()
        else:
            success = self._pollev_login()
        if not success:
            raise LoginError("Your username or password was incorrect.")
        logger.info("Login successful.")

    def get_firehose_token(self) -> str:
        """
        Given that the user is logged in, retrieve an AWS firehose token.
        If the poll host is not affiliated with UW, PollEv will return
        a firehose token with a null value.

        :raises ValueError: if the specified poll host is not found.
        """
        from uuid import uuid4
        # Before issuing a token, AWS checks for two visitor cookies that
        # PollEverywhere generates using js. They are random uuids.
        self.session.cookies['pollev_visitor'] = str(uuid4())
        self.session.cookies['pollev_visit'] = str(uuid4())
        url = endpoints['firehose_auth'].format(
            host=self.host,
            timestamp=self.timestamp()
        )
        r = self.session.get(url)
        logger.debug("firehose auth status=%s body=%s", r.status_code, r.text[:512])

        if "presenter not found" in r.text.lower():
            raise ValueError(f"'{self.host}' is not a valid poll host.")
        token = r.json().get('firehose_token')
        logger.debug("firehose auth token=%s", token)
        return token

    def get_new_poll_id(self, firehose_token=None) -> Optional[str]:
        import json

        if firehose_token:
            url = endpoints['firehose_with_token'].format(
                host=self.host,
                token=firehose_token,
                sequence=self.last_message_sequence,
                timestamp=self.timestamp()
            )
        else:
            url = endpoints['firehose_no_token'].format(
                host=self.host,
                sequence=self.last_message_sequence,
                timestamp=self.timestamp()
            )
        response_json = {}
        message = ''
        try:
            logger.debug("firehose request → %s", url)
            r = self.session.get(url, timeout=25)
            logger.debug("firehose status=%s cookies=%s", r.status_code, r.cookies.get_dict())
            logger.debug("firehose body=%s", r.text[:512])
            response_json = r.json()
            self._update_last_message_sequence(response_json.get('last_message_sequence'))
            message = response_json.get('message', '')
            if not message:
                logger.debug("firehose response missing message payload; raw json=%s", response_json)
                return None
            payload_json = json.loads(message)
            if not isinstance(payload_json, dict):
                logger.debug("firehose message payload not a dict; payload=%s raw json=%s",
                             payload_json, response_json)
                return None
            poll_id = payload_json.get('uid')
            if not poll_id:
                logger.debug("firehose message missing UID payload; message=%s raw json=%s",
                             message, response_json)
                return None
            self._update_last_message_sequence(payload_json.get('sequence'))
        # Firehose either doesn't respond or responds with no data if no poll is open.
        except requests.exceptions.ReadTimeout:
            logger.debug("firehose long-poll timed out (no new activity yet); will retry")
            return None
        except json.JSONDecodeError:
            logger.debug("firehose message payload was not valid JSON; message=%s raw json=%s",
                         message, response_json)
            return None
        logger.debug("firehose parsed poll_id=%s", poll_id)
        return poll_id

    def answer_poll(self, poll_id) -> dict:
        import random

        url = endpoints['poll_data'].format(uid=poll_id)
        poll_data = self.session.get(url).json()
        logger.debug("poll %s data keys=%s", poll_id, list(poll_data.keys()))
        options = poll_data['options'][self.min_option:self.max_option]
        logger.debug("poll %s options slice [%s:%s] -> %s choices",
                     poll_id, self.min_option, self.max_option,
                     len(options))
        try:
            option_id = random.choice(options)['id']
        except IndexError:
            # `options` was empty
            logger.error(f'Could not answer poll: poll only has '
                         f'{len(poll_data["options"])} options but '
                         f'self.min_option was {self.min_option} and '
                         f'self.max_option: {self.max_option}')
            return {}
        logger.debug("poll %s selected option_id=%s", poll_id, option_id)
        r = self.session.post(
            endpoints['respond_to_poll'].format(uid=poll_id),
            headers={'x-csrf-token': self._get_csrf_token()},
            data={'option_id': option_id, 'isPending': True, 'source': "pollev_page"}
        )
        logger.debug("poll %s respond status=%s body=%s",
                     poll_id, r.status_code, r.text[:512])
        return r.json()

    def alive(self):
        return time.time() <= self.start_time + self.lifetime

    def run(self):
        """Runs the script."""
        try:
            if self.session_cookies:
                logger.info("Using provided session cookies for authentication.")
                self.session.cookies.update(self.session_cookies)
                try:
                    # Prime CSRF/token state to validate the supplied cookies early.
                    _ = self._get_csrf_token()
                except Exception as exc:
                    logger.warning(f"CSRF preflight failed: {exc}")
            else:
                self.login()

            referer = endpoints['home'].format(host=self.host)
            self.session.headers['Referer'] = referer
            try:
                logger.debug("warming up session via %s", referer)
                self.session.get(referer, timeout=5)
            except Exception as exc:
                logger.debug("host warm-up failed (non-fatal): %s", exc)

            registration_url = f"https://pollev.com/proxy/api/users/{self.host}/participant_registration"
            try:
                logger.debug("attempting participant registration → %s", registration_url)
                self.session.post(
                    registration_url,
                    headers={'x-csrf-token': self._get_csrf_token()},
                    json={},
                    timeout=5
                )
            except Exception as exc:
                logger.debug("participant_registration failed or unavailable: %s", exc)

            token = self.firehose_token
            if token:
                logger.info("Using firehose token supplied via configuration.")
            else:
                token = self.get_firehose_token()
            if not token:
                logger.error(
                    "No firehose_token for '%s' after warm-up; verify the host is correct "
                    "and that this session has joined the presenter context.",
                    self.host
                )
                return
            self.firehose_token = token
            self.last_message_sequence = 0
        except (LoginError, ValueError) as e:
            logger.error(e)
            return

        while self.alive():
            poll_id = self.get_new_poll_id(self.firehose_token)

            if poll_id is None:
                logger.info(f'`{self.host}` has no new activity yet. Polling again shortly.')
                sleep_for = min(1.0, self.closed_wait)
                if sleep_for > 0:
                    logger.debug("sleeping for %s seconds before next firehose check", sleep_for)
                    time.sleep(sleep_for)
            else:
                logger.info(f"{self.host} has opened a new poll! "
                            f"Waiting {self.open_wait} seconds before responding.")
                time.sleep(self.open_wait)
                r = self.answer_poll(poll_id)
                if not r:
                    logger.warning("poll %s response payload empty; request likely failed", poll_id)
                logger.info(f'Received response: {r}')
