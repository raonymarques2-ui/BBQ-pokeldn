"""Registration only: importing this file never starts a host or touches a radio."""
from pokeldn.plugins import Field, Tool
from ucbbq.i18n import configure, tr


def register(api):
    configure()
    api.add_tool('sv', Tool(
        'uc-bbq-host', tr('name', 'Union Circle BBQ Host', 'Host de BBQs do Union Circle'), 'run.py',
        tr('summary', 'Earn a chosen amount of computed BP, then disband the group.',
           'Acumule a meta de BP calculados e desfaça o grupo ao terminar.'),
        (tr('step.setup', 'Select your ESP32 and keys in PokeLDN Settings. Keep Eden closed.',
            'Selecione o ESP32 e as chaves nas configurações do PokeLDN. Mantenha o Eden fechado.'),
         tr('step.game', 'Load the Terarium with BBQs unlocked on one physical Switch.',
            'Entre no Terarium com as BBQs liberadas em um Switch físico.'),
         tr('step.join', 'Press Start, then join local group 4970 manually.',
            'Inicie e entre manualmente no grupo local 4970.'),
         tr('step.run', 'The run starts when the world is ready. Avoid manual quests during the run.',
            'A rodada começa quando o mapa estiver pronto. Evite fazer missões manualmente durante a rodada.'),
         tr('step.sandwich', 'Gold sandwich quests are skipped; blue and red quests continue.',
            'A dourada de sandwich é ignorada; azuis e vermelhas continuam.')),
        fields=(
            Field('--bp-target', tr('field.target', 'Target BP earned', 'Meta de BP ganhos'), 'number', default='1000', required=True,
                  help=tr('help.target', 'BP earned during this run, not the console balance. The final reward may exceed the target.',
                          'BP ganhos nesta rodada. A última recompensa pode ultrapassar a meta.')),
            Field('--interval', tr('field.interval', 'Seconds between completions', 'Segundos entre conclusões'), 'number', default='3', hidden=True,
                  help=tr('help.interval', 'At least three seconds. Only one completion may be pending.',
                          'No mínimo três segundos. Apenas uma conclusão pode ficar pendente.')),
        ),
    ))
