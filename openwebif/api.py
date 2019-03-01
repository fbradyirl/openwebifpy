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
from xml.etree import ElementTree

from enum import Enum
import requests
from requests.exceptions import ConnectionError as ReConnError

from openwebif.constants import DEFAULT_PORT
from openwebif.error import OpenWebIfError, MissingParamError

_LOGGER = logging.getLogger(__name__)

URL_ABOUT = "/web/about"
URL_TOGGLE_VOLUME_MUTE = "/web/vol?set=mute"
URL_SET_VOLUME = "/api/vol?set=set"
URL_TOGGLE_STANDBY = "/api/powerstate?newstate=0"
URL_STATUS_INFO = "/api/statusinfo"

# Remote control commands
URL_REMOTE_CONTROL = "/api/remotecontrol?command="
COMMAND_VU_CHANNEL_UP = "402"
COMMAND_VU_CHANNEL_DOWN = "403"
COMMAND_VU_PLAY_PAUSE_TOGGLE = "207"

URL_LCD_4_LINUX = "/lcd4linux/dpf.png"


class PlaybackType(Enum):
    """ Enum for Playback Type """
    live = 1
    recording = 2
    none = 3


# pylint: disable=too-many-arguments


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


class CreateDevice(object):
    """
    Create a new OpenWebIf client device.
    """

    def __init__(self, host=None, port=DEFAULT_PORT,
                 username=None, password=None, is_https=False):
        enable_logging()
        _LOGGER.info("Initialising new openwebif client")

        if not host:
            _LOGGER.error('Missing Openwebif host!')
            raise MissingParamError('Connection to OpenWebIf failed.', None)

        self._session = requests.Session()
        self._session.auth = (username, password)

        # Used to build a list of URLs which have been tested to exist
        # (for picons)
        self.cached_urls_which_exist = []

        # Now build base url
        protocol = 'http' if not is_https else 'https'
        self._base = '{}://{}:{}'.format(protocol, host, port)

        self._in_standby = False
        try:
            _LOGGER.info("Going to probe device to test connection")
            version = self.get_version()
            _LOGGER.info("Connected OK!")
            _LOGGER.info("OpenWebIf version %s", version)

        except ReConnError as conn_err:
            raise OpenWebIfError('Connection to OpenWebIf failed.', conn_err)

    def set_volume(self, new_volume):
        """
        Sets the volume to the new value

        :param new_volume: int from 0-100
        :return: True if successful, false if there was a problem
        """

        assert -1 << new_volume << 101, "Volume must be between " \
                                        "0 and 100"

        url = '%s%s%s' % (self._base, URL_SET_VOLUME, str(new_volume))
        _LOGGER.info('url: %s', url)

        return self._check_reponse_result(self._session.get(url))

    def toggle_standby(self):
        """
        Returns True if command success, else, False
        """

        url = '%s%s' % (self._base, URL_TOGGLE_STANDBY)
        _LOGGER.info('url: %s', url)

        result = self._check_reponse_result(self._session.get(url))
        # Update standby
        self.get_status_info()
        return result

    def toggle_play_pause(self):
        """
        Send Play Pause command
        """

        url = '%s%s%s' % (self._base, URL_REMOTE_CONTROL,
                          COMMAND_VU_PLAY_PAUSE_TOGGLE)
        _LOGGER.info('url: %s', url)

        return self._check_reponse_result(self._session.get(url))

    def set_channel_up(self):
        """
        Send channel up command
        """

        url = '%s%s%s' % (self._base, URL_REMOTE_CONTROL,
                          COMMAND_VU_CHANNEL_UP)
        _LOGGER.info('url: %s', url)

        return self._check_reponse_result(self._session.get(url))

    def set_channel_down(self):
        """
        Send channel down command
        """

        url = '%s%s%s' % (self._base, URL_REMOTE_CONTROL,
                          COMMAND_VU_CHANNEL_DOWN)
        _LOGGER.info('url: %s', url)

        return self._check_reponse_result(self._session.get(url))

    def mute_volume(self):
        """
        Send mute command
        """
        url = '%s%s' % (self._base, URL_TOGGLE_VOLUME_MUTE)
        _LOGGER.info('url: %s', url)

        response = self._session.get(url)
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

    def is_box_in_standby(self):
        """
        Returns True if box is now in standby, else, False
        """
        return self._in_standby

    def get_about(self, element_to_query=None, timeout=None):
        """
        Returns ElementTree containing the result of <host>/web/about
        or if element_to_query is not None, the value of that element
        """

        url = '%s%s' % (self._base, URL_ABOUT)
        _LOGGER.info('url: %s', url)

        if timeout is not None:
            response = self._session.get(url, timeout=timeout)
        else:
            response = self._session.get(url)

        if response.status_code != 200:
            log_response_errors(response)
            raise OpenWebIfError('Connection to OpenWebIf failed.')

        if element_to_query is None:
            return response.content
        else:
            try:
                tree = ElementTree.fromstring(response.content)
                result = tree.findall(".//" + element_to_query)

                if len(result) > 0:
                    _LOGGER.info('element_to_query: %s result: %s',
                                 element_to_query, result[0])

                    return result[0].text.strip()
                else:
                    _LOGGER.error(
                        'There was a problem finding element: %s',
                        element_to_query)

            except AttributeError as attib_err:
                _LOGGER.error(
                    'There was a problem finding element:'
                    ' %s AttributeError: %s', element_to_query, attib_err)
                _LOGGER.error('Entire response: %s', response.content)
                return
        return

    def refresh_status_info(self):
        """
        Returns json containing the result of <host>/api/statusinfo
        """
        return self.get_status_info()

    def get_status_info(self):
        """
        Returns json containing the result of <host>/api/statusinfo
        """

        url = '%s%s' % (self._base, URL_STATUS_INFO)
        _LOGGER.info('url: %s', url)

        response = self._session.get(url)

        if response.status_code != 200:
            _LOGGER.info("status_code %s", response.status_code)
            log_response_errors(response)
            self._in_standby = True
            raise OpenWebIfError('Connection to OpenWebIf failed.')

        _LOGGER.info('response: %s', response.json())

        if 'inStandby' in response.json():
            self._in_standby = response.json()['inStandby'] == 'true'

        return response.json()

    def get_current_playback_type(self, currservice_serviceref=None):
        """
        Get the currservice_serviceref playing media type.

        :param currservice_serviceref: If you already know the
        currservice_serviceref pass it here, else it will be
        determined
        :return: PlaybackType.live or PlaybackType.recording
        """

        if currservice_serviceref is None:

            if self.is_box_in_standby():
                return PlaybackType.none

            status_info = self.get_status_info()
            if 'currservice_serviceref' in status_info:
                currservice_serviceref = status_info['currservice_serviceref']

        if currservice_serviceref.startswith('1:0:0'):
            # This is a recording, not a live channel
            return PlaybackType.recording

        return PlaybackType.live

    def get_current_playing_picon_url(self, channel_name=None,
                                      currservice_serviceref=None):
        """
        Return the URL to the picon image for the currently playing channel

        :param channel_name: If specified, it will base url on this channel
        name else, fetch latest from get_status_info()
        :param currservice_serviceref: The service_ref for the current service
        :return: The URL, or None if not available
        """
        cached_info = None
        if channel_name is None:
            cached_info = self.get_status_info()
            if 'currservice_station' in cached_info:
                channel_name = cached_info['currservice_station']
            else:
                _LOGGER.info('No channel currently playing')
                return None

        if currservice_serviceref is None:
            if cached_info is None:
                cached_info = self.get_status_info()
            currservice_serviceref = cached_info['currservice_serviceref']

        if currservice_serviceref.startswith('1:0:0'):
            # This is a recording, not a live channel

            # Todo: parse channel name from currservice_serviceref
            # and get picon based on that

            # As a fallback, send LCD4Linux image (if available)
            url = '%s%s' % (self._base, URL_LCD_4_LINUX)
            _LOGGER.info('This is a recording, trying url: %s', url)

        else:
            picon_name = self.get_picon_name(channel_name)
            url = '%s/picon/%s.png' % (self._base, picon_name)

        if url in self.cached_urls_which_exist:
            _LOGGER.info('picon url (already tested): %s', url)
            return url

        if self.url_exists(url):
            _LOGGER.info('picon url: %s', url)
            return url

        # Last ditch attenpt. If channel ends in HD, lets try
        # and get non HD picon
        if channel_name.lower().endswith('hd'):
            channel_name = channel_name[:-2]
            _LOGGER.info('Going to look for non HD picon for: %s',
                         channel_name)
            return self.get_current_playing_picon_url(
                ''.join(channel_name.split()),
                currservice_serviceref)

        _LOGGER.info('Could not find picon for: %s', channel_name)
        return None

    def url_exists(self, url):
        """
        Check if a given URL responds to a HEAD request
        :param url: url to test
        :return: True or False
        """
        request = self._session.head(url)
        if request.status_code == 200:
            self.cached_urls_which_exist.append(url)
            _LOGGER.debug('cached_urls_which_exist: %s',
                          str(self.cached_urls_which_exist))
            return True

        return False

    @staticmethod
    def get_picon_name(channel_name):
        """
        Get the name as format is outlined here
        https://github.com/OpenViX/enigma2/blob/cc963cd25d7e1c58701f55aa4b382e525031966e/lib/python/Components/Renderer/Picon.py

        :param channel_name: The name of the channel
        :return: the correctly formatted name
        """
        _LOGGER.info("Getting Picon URL for : " + channel_name)

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
        return self.get_about(
            element_to_query='e2webifversion', timeout=5)
