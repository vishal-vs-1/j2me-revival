"""Exact-file compatibility profiles. Other JARs retain a selectable default screen."""
PROFILES={
    '061f71e5ad66befade2c6d2bbcca1e5a76c4cf9a7782f82cd80ab8a1e4cc56d6': {
        'width':176,'height':220,
        'screen_source':'profile',
        'text_resources':['c1.png','c2.png'],
        'runtime_compat':{'repaint_on_show':True,'restore_movement_canvases':['p'],
                          'restore_movement_state':'p:cT:7'},
        'screen_note':'176 × 220 artwork variant; s.png is a full-screen 176 × 220 image',
        'startup_hint':'Select Play Game. On Syncing with server, Q selects Goto Game.'
    }
}
