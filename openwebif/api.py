"""
openwebif.api
~~~~~~~~~~~~~~~~~~~~

Provides methods for interacting with OpenWebIf

Copyright (c) 2015 Finbarr Brady <https://github.com/fbradyirl>
Licensed under the MIT license.
"""

import logging
import re
import unicodedata
import urllib
from enum import Enum
from random import randint

import requests

from openwebif.error import OpenWebIfError, MissingParamError

_LOGGER = logging.getLogger(__name__)

URL_ABOUT = "/api/about"
URL_TOGGLE_VOLUME_MUTE = "/web/vol?set=mute"
URL_SET_VOLUME = "/api/vol?set=set"
URL_MESSAGE = "/api/message?timeout={}&type={}&text={}"

# newstate - (optional) number; one of
# 0: Toggle StandBy
# 1: DeepStandBy
# 2: Reboot
# 3: Restart Enigma
# 4: Wakeup
# 5: Standby

URL_POWERSTATE_BASE = "/api/powerstate?newstate="
TOGGLE_STANDBY = "0"
DEEP_STANDBY = "1"
WAKEUP = "4"
STANDBY = "5"

URL_STATUS_INFO = "/api/statusinfo"
URL_EPG_NOW = "/api/epgnow?bRef="
URL_GET_ALL_SERVICES = "/api/getallservices"
URL_GET_ALL_BOUQUETS = "/api/bouquets"
URL_ZAP_TO_SOURCE = "/api/zap?sRef="
URL_GRAB_720 = "/grab?format=jpg&r=720&mode=all&T="

# Remote control commands
URL_REMOTE_CONTROL = "/api/remotecontrol?command="
COMMAND_VU_CHANNEL_UP = "402"
COMMAND_VU_CHANNEL_DOWN = "403"
COMMAND_VU_PLAY_PAUSE_TOGGLE = "207"
COMMAND_VU_STOP = "128"

URL_LCD_4_LINUX = "/lcd4linux/dpf.png"


class PlaybackType(Enum):
    """ Enum for Playback Type """
    live = 1
    recording = 2
    none = 3


class MessageType(Enum):
    """ Enum for Message Type """
    YESNO = "0"
    INFO = "1"
    WARNING = "2"
    ERROR = "3"


def log_response_errors(response):
    """
    Logs problems in a response
    """

    _LOGGER.error("status_code %s", response.status_code)
    if response.error:
        _LOGGER.error("error %s", response.error)


def enable_logging():
    """ Setup the logging for home assistant. """
    logging.basicConfig(level=logging.INFO)


# pylint: skip-file
class CreateDevice:
    """
    Create a new OpenWebIf client device.
    """

    # pylint: disable=too-many-arguments, disable=too-many-instance-attributes
    def __init__(self, host=None, port=None,
                 username=None, password=None, is_https=False,
                 prefer_picon=False, mac_address=None,
                 turn_off_to_deep=False, source_bouquet=None,
                 message_display_timeout=None):
        """
        Defines an enigma2 device.

        :param host: IP or hostname
        :param port: OpenWebif port
        :param username: e2 user
        :param password: e2 user password
        :param is_https: use https or not
        :param prefer_picon: if yes, return picon instead of screen grab
        :param mac_address: if set, send WOL packet on power on.
        :param turn_off_to_deep: If True, send to deep standby on turn off
        :param source_bouquet: Which bouquet ref you want to load
        :param message_display_timeout: The display timeout for the notification
        """
        enable_logging()

        if not host:
            _LOGGER.error('Missing Openwebif host!')
            raise MissingParamError('Connection to OpenWebIf failed.', None)

        _LOGGER.debug(f"Initialising new openwebif client for host: {host}")
        _LOGGER.debug(f"{host} Using a single session client.")
        self.session = requests.Session()
        self.session.auth = (username, password)

        # Used to build a list of URLs which have been tested to exist
        # (for picons)
        self.cached_urls_which_exist = []
        self.prefer_picon = prefer_picon
        self.mac_address = mac_address
        self.turn_off_to_deep = turn_off_to_deep

        # Now build base url
        protocol = 'http' if not is_https else 'https'

        if port is not None:
            self._base = f"{protocol}://{host}:{port}"
        else:
            self._base = f"{protocol}://{host}"

        self.in_standby = True
        self.is_offline = False

        self.state = None
        self.volume = None
        self.current_service_channel_name = None
        self.current_programme_name = None
        self.current_service_ref = None
        self.muted = False
        self.picon_url = None
        self.status_info = {}
        self.is_recording_playback = False
        self.source_bouquet = source_bouquet
        self.sources = None
        self.source_list = None
        self.message_display_timeout = message_display_timeout
        self.get_version()

    def default_all(self):
        """Default all the props."""
        self.state = None
        self.volume = None
        self.in_standby = True
        self.current_service_channel_name = None
        self.current_programme_name = None
        self.current_service_ref = None
        self.muted = False
        self.picon_url = None
        self.status_info = {}
        self.is_recording_playback = False

    def send_message(self, text: str, message_type: MessageType = MessageType.INFO):
        """
        Sends a message to the TV screen.

        :param text: The message to display
        :param message_type: The type of message (0 = YES/NO, 1 = INFO, 2 = WARNING, 3 = ERROR)
        :return: True if successful, false if there was a problem
        """

        url = self._base + \
              URL_MESSAGE.format(
                  str(self.message_display_timeout or -1), message_type.value, requests.utils.quote(text))
        _LOGGER.debug('url: %s', url)

        return self._check_reponse_result(self._session.get(url))

    def set_volume(self, new_volume):
        """
        Sets the volume to the new value

        :param new_volume: int from 0-100
        :return: True if successful, false if there was a problem
        """

        url = '%s%s%s' % (self._base, URL_SET_VOLUME, str(new_volume))
        _LOGGER.debug('url: %s', url)

        return self._check_reponse_result(self.session.get(url))

    def turn_on(self):
        """
        Take the box out of standby.
        """

        if self.is_offline:
            _LOGGER.debug('Box is offline, going to try wake on lan')
            self.wake_up()

        url = '{}{}{}'.format(self._base, URL_POWERSTATE_BASE, WAKEUP)
        _LOGGER.debug('Wakeup box from standby. url: %s', url)

        result = self._check_reponse_result(self.session.get(url))
        return result

    # pylint: disable=import-outside-toplevel
    def wake_up(self):
        """Send WOL packet to the mac."""
        if self.mac_address:
            from wakeonlan import send_magic_packet
            send_magic_packet(self.mac_address)
            _LOGGER.debug("Sent WOL magic packet to %s", self.mac_address)
            return True

        _LOGGER.warning("Cannot wake up host as mac_address is not known.")
        return False

    def turn_off(self):
        """
        Put the box out into standby.

        if turn_off_to_deep is True, go to deep standby.
        """
        if self.turn_off_to_deep:
            return self.deep_standby()

        url = '{}{}{}'.format(self._base, URL_POWERSTATE_BASE, STANDBY)
        _LOGGER.debug('Going into standby. url: %s', url)

        result = self._check_reponse_result(self.session.get(url))
        return result

    def deep_standby(self):
        """
        Go into deep standby.
        """

        url = '{}{}{}'.format(self._base, URL_POWERSTATE_BASE, DEEP_STANDBY)
        _LOGGER.debug('url: %s', url)

        try:
            self.session.get(url)
        # pylint: disable=broad-except
        except Exception:
            # As there is no proper response, an exception
            # means the box is now gone down
            return True
        return False

    def toggle_play_pause(self):
        """
        Send Play Pause command
        """

        url = '%s%s%s' % (self._base, URL_REMOTE_CONTROL,
                          COMMAND_VU_PLAY_PAUSE_TOGGLE)
        _LOGGER.debug('url: %s', url)

        return self._check_reponse_result(self.session.get(url))

    def set_channel_up(self):
        """
        Send channel up command
        """

        url = '%s%s%s' % (self._base, URL_REMOTE_CONTROL,
                          COMMAND_VU_CHANNEL_UP)
        _LOGGER.debug('url: %s', url)

        return self._check_reponse_result(self.session.get(url))

    def set_channel_down(self):
        """
        Send channel down command
        """

        url = '%s%s%s' % (self._base, URL_REMOTE_CONTROL,
                          COMMAND_VU_CHANNEL_DOWN)
        _LOGGER.debug('url: %s', url)

        return self._check_reponse_result(self.session.get(url))

    def set_stop(self):
        """
        Send stop command
        """

        url = '%s%s%s' % (self._base, URL_REMOTE_CONTROL,
                          COMMAND_VU_STOP)
        _LOGGER.debug('url: %s', url)

        return self._check_reponse_result(self.session.get(url))

    def mute_volume(self):
        """
        Send mute command
        """
        url = '%s%s' % (self._base, URL_TOGGLE_VOLUME_MUTE)
        _LOGGER.debug('url: %s', url)

        response = self.session.get(url)
        if response.status_code != 200:
            return False

        # Dont want to deal with ElementTree, return true
        return True

    @staticmethod
    def _check_reponse_result(response):
        """

        :param response:
        :return: Returns True if command success, else, False
        """

        if response.status_code != 200:
            log_response_errors(response)
            raise OpenWebIfError('Connection to OpenWebIf failed.')

        return response.json()['result']

    def update(self):
        """
        Refresh current state based from <host>/api/statusinfo
        """
        self.status_info = self._call_api(f"{self._base}{URL_STATUS_INFO}")

        if not self.sources:
            self.sources = self.get_bouquet_sources(
                bouquet=self.source_bouquet)
            self.source_list = list(self.sources.keys())

        if self.is_offline or not self.status_info:
            self.default_all()
            return

        if 'inStandby' in self.status_info:
            self.in_standby = self.status_info['inStandby'] == 'true'

        if not self.in_standby and not self.is_offline and 'currservice_serviceref' in self.status_info:  # noqa: E501
            self.current_service_ref = self.status_info['currservice_serviceref']  # noqa: E501
            self.is_recording_playback = self.is_currently_recording_playback()

            pname = self.status_info['currservice_name']
            if self.is_recording_playback:
                # try get correct channel name
                channel_name = self.get_channel_name_from_serviceref()
                self.status_info['currservice_station'] = channel_name
                self.current_service_channel_name = channel_name
                self.current_programme_name = "🔴 {}".format(pname)
            else:
                self.current_service_channel_name = self.status_info[
                    'currservice_station']
                self.current_programme_name = pname if pname != "N/A" else ""

            self.muted = self.status_info['muted']
            self.volume = self.status_info['volume'] / 100
            self.picon_url = \
                self.get_current_playing_picon_url(
                    channel_name=self.current_service_channel_name,
                    currservice_serviceref=self.current_service_ref)
        else:
            self.default_all()

    def is_currently_recording_playback(self):
        """Returns true if playing back recording."""
        return self.get_current_playback_type() == PlaybackType.recording

    def get_current_playback_type(self):
        """
        Get the currservice_serviceref playing media type.

        :return: PlaybackType.live or PlaybackType.recording
        """

        if self.current_service_ref:
            if self.current_service_ref.startswith('1:0:0'):
                # This is a recording, not a live channel
                return PlaybackType.recording

            return PlaybackType.live
        return None

    def get_current_playing_picon_url(self, channel_name=None,
                                      currservice_serviceref=None):
        """
        Return the URL to the picon image for the currently playing channel.

        :param channel_name: If specified, it will base url on this channel
        name else, fetch latest from get_status_info()
        :param currservice_serviceref: The service_ref for the current service
        :return: The URL, or None if not available
        """
        cached_info = None
        if channel_name is None:
            cached_info = self.status_info
            if 'currservice_station' in cached_info:
                channel_name = cached_info['currservice_station']
            else:
                _LOGGER.debug('No channel currently playing')
                return None

        if currservice_serviceref is None:
            if cached_info is None:
                cached_info = self.status_info
            currservice_serviceref = cached_info['currservice_serviceref']

        if self.is_recording_playback:
            channel_name = self.get_channel_name_from_serviceref()

        if self.prefer_picon:

            picon_name = self.get_picon_name(channel_name)
            url = '%s/picon/%s.png' % (self._base, picon_name)
            _LOGGER.debug('trying picon url (by channel name): %s', url)
            if self.url_exists(url):
                return url

            # If channel ends in HD, lets try
            # and get non HD picon
            if channel_name.lower().endswith('hd'):
                channel_name = channel_name[:-2]
                _LOGGER.debug('Going to look for non HD picon for: %s',
                              channel_name)
                return self.get_current_playing_picon_url(
                    ''.join(channel_name.split()),
                    currservice_serviceref)

            # Last ditch attempt.
            # Now try old way, using service ref name.
            # See https://github.com/home-assistant/home-assistant/issues/22293
            #
            # e.g.
            # sref: "1:0:19:2887:40F:1:C00000:0:0:0:"
            # url: http://vusolo2/picon/1_0_19_2887_40F_1_C00000_0_0_0.png)
            picon_file_name = currservice_serviceref. \
                strip(":").replace(":", "_")
            url = '%s/picon/%s.png' % (self._base, picon_file_name)
            _LOGGER.debug('trying picon url (with sref): %s', url)
            if self.url_exists(url):
                return url

            _LOGGER.debug('Could not find picon for: %s', channel_name)

            # stop here. Some boxes freeze when attempting screen grabs so often.
            # See https://github.com/fbradyirl/openwebifpy/issues/14
            return None

        _LOGGER.debug('prefer_picon is False. Returning '
                      'screengrab of channel: %s', channel_name)

        # Lastly, just return screen grab
        # random number at the end so image doesnt get cached
        url = "{}{}{}".format(self._base, URL_GRAB_720,
                              randint(1000000000, 9999999999))
        if self.url_exists(url):
            _LOGGER.debug('Instead of picon, returning '
                          'screen grab url: %s', url)
            return url

        return None

    def get_channel_name_from_serviceref(self):
        """

        :param currservice_serviceref:
        :return:
        """
        try:
            return self.current_service_ref.split('-')[1].strip()
        # pylint: disable=broad-except
        except Exception:
            _LOGGER.debug("cannot determine channel name from recording")
        return self.current_service_ref

    def url_exists(self, url):
        """
        Check if a given URL responds to a HEAD request
        :param url: url to test
        :return: True or False
        """

        if url in self.cached_urls_which_exist:
            _LOGGER.debug('picon url (already tested): %s', url)
            return True

        request = self.session.head(url)
        if request.status_code == 200:
            self.cached_urls_which_exist.append(url)
            _LOGGER.debug('cached_urls_which_exist: %s',
                          str(self.cached_urls_which_exist))
            return True

        _LOGGER.debug('url at %s does not exist.', url)
        return False

    @staticmethod
    def get_picon_name(channel_name):
        """
        Get the name as format is outlined here
        https://github.com/OpenViX/enigma2/blob/cc963cd25d7e1c58701f55aa4b382e525031966e/lib/python/Components/Renderer/Picon.py

        :param channel_name: The name of the channel
        :return: the correctly formatted name
        """
        _LOGGER.debug("Getting Picon URL for %s", channel_name)

        channel_name = unicodedata.normalize('NFKD', channel_name) \
            .encode('ASCII', 'ignore')
        channel_name = channel_name.decode("utf-8")
        exclude_chars = ['/', '\\', '\'', '"', '`', '?', ' ', '(', ')', ':',
                         '<', '>', '|', '.', '\n']
        channel_name = re.sub('[%s]' % ''.join(exclude_chars), '',
                              channel_name)
        channel_name = channel_name.replace('&', 'and')
        channel_name = channel_name.replace('+', 'plus')
        channel_name = channel_name.replace('*', 'star')
        channel_name = channel_name.lower()

        return channel_name

    def get_version(self):
        """
        Returns Openwebif version
        """
        url = f"{self._base}{URL_ABOUT}"
        _LOGGER.debug('url: %s', url)
        result = self._call_api(url)

        if self.is_offline or not result:
            _LOGGER.warning(f"{self._base}: Cannot get version as box is unreachable.")
            return ''

        _LOGGER.debug(f"{self._base}: Connected OK. About Response: {result}")
        version = result['info']['webifver']
        _LOGGER.info(f"{self._base}: OpenWebIf version %s", version)
        # Discover the mac, so we can WOL the box
        # later if needed
        if not self.mac_address:
            ifaces = result['info']['ifaces']
            _LOGGER.debug('ifaces: %s', ifaces)

            for iface in ifaces:
                # Only if it is an eth interface
                # (wol doesnt work on wireless)
                if iface['name'].startswith("eth"):
                    self.mac_address = iface['mac']
                    _LOGGER.debug('discovered %s mac_address: %s',
                                  iface['name'],
                                  self.mac_address)

        return version

    def get_bouquet_sources(self, bouquet=None):
        """
        Get a dict of source names and sources in the bouquet.

        If bouquet is None, the first bouquet will be read from.

        :param bouquet: The bouquet
        :return: a dict
        """
        sources = {}

        if not bouquet:
            # load first bouquet
            all_bouquets = self.get_all_bouquets()
            if not all_bouquets:
                _LOGGER.debug(f"{self._base} get_all_bouquets: No bouquets were found.")
                return sources

            if 'bouquets' in all_bouquets:
                bouquet = all_bouquets['bouquets'][0][0]
                first_bouquet_name = all_bouquets['bouquets'][0][1]
                _LOGGER.debug(f"{self._base} First bouquet name is: '%s'",
                              first_bouquet_name)
            else:
                _LOGGER.debug("bouquets not in all_bouquets.")
                return sources
        else:
            _LOGGER.info(f"{self._base} User defined bouquet to load: {bouquet}")

        url = f"{self._base}{URL_EPG_NOW}{bouquet}"
        _LOGGER.debug(f"{self._base} loading sources from bouquet. {url}")
        result = self._call_api(url)

        if result:
            events = result['events']
            source_names = [src['sname'] for src in events]
            source_refs = [src['sref'] for src in events]

            sources = dict(zip(source_names, source_refs))
        else:
            _LOGGER.warning("No sources could be loaded "
                            "from specified bouquet.")

        _LOGGER.debug(f"{self._base} sources: {sources}")
        return sources

    def get_all_services(self):
        """Get list of all services."""
        return self._call_api(f"{self._base}{URL_GET_ALL_SERVICES}")

    def get_all_bouquets(self):
        """Get list of all bouquets."""
        return self._call_api(f"{self._base}{URL_GET_ALL_BOUQUETS}")

    def select_source(self, source):
        """
        Change channel to selected source

        :param source: the sRef of the channel.
        """
        sref_url_encoded = urllib.parse.quote_plus(source)
        return self._call_api(f"{self._base}{URL_ZAP_TO_SOURCE}{sref_url_encoded}")  # noqa: E501

    def _call_api(self, url):
        """Perform one api request operation."""

        try:
            response = self.session.get(url)
        except requests.exceptions.ConnectionError as err:
            if not self.is_offline:
                _LOGGER.error(f"There was a connection error calling {url}"
                          f" Please check the network connection to the Enigma2"
                          f" box is ok and enable debug logging in "
                          f"Enigma2 if required. Error: {err}")
                self.is_offline = True
            return None

        _LOGGER.debug(f"Got {response.status_code} from : %s", url)
        if response.status_code not in [200]:
            error_msg = "Got {} from {}: {}".format(
                response.status_code, url, response.text)
            _LOGGER.error(error_msg)

            # If box is in deep standby, dont raise this
            # over and over. (Too late here)
            #if not self.is_offline:
            #    message = f"{url} is unreachable."
            #    _LOGGER.warning(message)
            #    self.is_offline = True
            return None

        self.is_offline = False
        if response.status_code == 200:
            return response.json()

        if response.status_code == 401:
            raise Exception(f"{url}: Failed to authenticate "
                            "with OpenWebIf "
                            "check your "
                            "username and password.")
        if response.status_code == 404:
            raise Exception(f"Got a 404 from {url}. Do"
                            "you have the OpenWebIf plugin"
                            "installed?")

        _LOGGER.error("Invalid response from "
                      "OpenWebIf: %s", response)
        return None
