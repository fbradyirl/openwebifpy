=====
Usage
=====

To use openwebifpy in a project::

    import openwebif.api
    client = openwebif.api.CreateDevice('vuduo2.local')
    sources = client.get_bouquet_sources()
    picon_url = client.get_current_playing_picon_url()
    client.toggle_standby()
    client.toggle_play_pause()
    client.set_channel_up()
