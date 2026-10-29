"""Per-game JVM execution policy, independent of artwork, rendering and key mapping."""


def java_execution_arguments(game):
    mode=game.get('execution_mode','normal')
    if mode=='normal':return []
    # Keep C1 compilation for image loading/rendering. Full interpretation made
    # the entire enhanced player slow before its first game frame. The former
    # stored name remains an alias so existing opt-in settings are repaired.
    if mode in ('compatible','interpreted'):return ['-XX:TieredStopAtLevel=1']
    raise ValueError('Unknown Java execution mode. Choose Normal or Compatibility.')
