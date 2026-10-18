"""Use PokeLDN's selected application language, never a plugin language setting."""
_locale = ''


def selected_language():
    # settings.load() creates/saves defaults if absent. Registration must remain
    # read-only, including under PokeLDN's plugin filesystem guard.
    import json
    from pokeldn.app.paths import DATA
    try:
        values=json.loads((DATA/'settings.json').read_text(encoding='utf-8'))
        value=values.get('app_language','') if isinstance(values,dict) else ''
        return value if isinstance(value,str) else ''
    except (OSError,ValueError):
        return ''


def configure(*, select_runtime=False):
    global _locale
    from pokeldn import plugins
    from pokeldn.app import i18n
    selected = selected_language()
    _locale = ''
    for pack in plugins.discover():
        if (pack.id == selected and pack.locale and not pack.error
                and (plugins.named(pack) or pack.id in plugins.enabled())
                and plugins.compatibility(pack.api)[0] in ('ok', 'deprecated')):
            _locale = pack.locale.lower()
            break
    # GUI registration already has the application's translation selection.
    # A tool child needs to select the same pack for its native status cards.
    if select_runtime:
        i18n.select(selected)


def tr(key, english, portuguese=None):
    from pokeldn.app.i18n import t
    fallback = portuguese if _locale.split('-')[0] == 'pt' and portuguese else english
    return t('plugins.union_circle_bbq.' + key, fallback)
