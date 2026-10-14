"""Per-Minescript-process diagnostic policy; normal sessions always start strict."""
diagnostic_only=False


def configure(value):
    global diagnostic_only
    if type(value) is not bool:raise ValueError('Diagnostic policy must be boolean')
    diagnostic_only=value


def live_issues(active,paused,screen):
    return paused or screen is not None or (not active and not diagnostic_only)
