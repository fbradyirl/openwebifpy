"""
tests.test_api
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tests the api

Copyright (c) 2015 Finbarr Brady <https://github.com/fbradyirl>
Licensed under the MIT license.
"""
# pylint: disable=protected-access
import unittest

import openwebif.api
from openwebif.error import OpenWebIfError, MissingParamError


class TestAPI(unittest.TestCase):
    """ Tests openwebif.api module. """

    def test_create(self):
        """ Test creating a new device. """
        # Bogus config
        self.assertRaises(MissingParamError, lambda: openwebif.api.CreateDevice())
        # self.assertRaises(OpenWebIfError, lambda: openwebif.api.CreateDevice('10.10.10.4'))

    def test_get_picon_name(self):
        self.assertEqual(openwebif.api.CreateDevice.get_picon_name('RTÉ One'), "rteone")

    # def test_status(self):
    #     """ Test getting version and status. """
    #     # Use this to test on real box
    #     client = openwebif.api.CreateDevice('vuduo2.local')
    #     self.assertEqual("OWIF 1.3.6", client.get_version())
    #     self.assertTrue(len(client.get_status_info()) > 8)

    #     # Test that an exception doesnt get thrown
    #     result = client.is_box_in_standby()
    #     self.assertTrue(result is True or result is False)
