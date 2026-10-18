"""Catalogue-driven BBQ transitions, modeled from controlled reference captures.

This module performs no network or memory I/O. The physical client remains the
authority for applying received rewards. Unknown completion fields retain the
observed neutral values; the protocol is still experimental.
"""
from ucbbq.bbq_catalog import Catalog
from ucbbq.bbq_wire import BBQMessage,Signed16,WireError,validate_state

EMPTY=(0,0.0,0,0)
EMPTY_INFO=(0,0,0,Signed16(32767),0,0,0,0,0,0.0)


def validate_condition(grade,quest):
    # Type 33's parameter is a one-based biome ID. Zero is not a usable
    # biome, despite being a valid condition for unrelated quest families.
    if grade==0 and quest[0]==33 and quest[2] not in (1,2,3,4):
        raise WireError('Biome photo quest requires a captured biome ID from 1 to 4')
    if grade==2 and quest[0] in (15,25) and quest[2]!=2:
        raise WireError('This group quest requires the currently captured condition 2')


def signed(value):
    return value if value<128 else Signed16(value)


def descriptor(mission):
    result=list(mission.descriptor())
    # The reference serializes these signed game-table fields with tag 0x85
    # when they do not fit an immediate value, including 500-yard goals.
    for index in (3,4,5):result[index]=signed(result[index])
    return tuple(result)


def completion_bundle(state,index,station,revision,replacement=EMPTY,
                      bonus=EMPTY,group=EMPTY,extension=(),catalog=None):
    catalog=catalog or Catalog();validate_state(state)
    if index not in (1,2,3,5,6):raise WireError('Invalid quest slot')
    grade=0 if index<4 else 1 if index==5 else 2
    old=state[index];mission=catalog.lookup(grade,old)
    validate_condition(grade,old)
    if not mission.automatic_allowed:raise WireError('Gold sandwich completion is excluded')
    if not 0<=old[1]<mission.goal:raise WireError('Quest is not pending')
    if type(station) is not int or not 0<=station<2**64:raise WireError('Invalid live station')
    updated=list(state)
    new_info=EMPTY_INFO;bonus_info=EMPTY_INFO;group_info=EMPTY_INFO
    if grade==0:
        new_mission=catalog.lookup(0,replacement)
        validate_condition(0,replacement)
        if replacement[1]!=0.0:raise WireError('Replacement must start at zero')
        updated[index]=replacement;new_info=descriptor(new_mission)
        updated[7]=(state[7]+1)%10
        if updated[7]==0 and not state[5][0]:
            bonus_info=descriptor(catalog.lookup(1,bonus));updated[5]=bonus
        elif bonus!=EMPTY:raise WireError('Unexpected bonus generation')
    elif grade==1:
        updated[5]=EMPTY;updated[8]=(state[8]+1)%3
        if updated[8]==0 and not state[6][0]:
            group_mission=catalog.lookup(2,group)
            validate_condition(2,group)
            group_info=descriptor(group_mission);updated[6]=group
        elif group!=EMPTY:raise WireError('Unexpected group generation')
    else:
        updated[6]=EMPTY
        if replacement!=EMPTY or bonus!=EMPTY or group!=EMPTY:
            raise WireError('Unexpected group replacement')
    updated[9 if grade<2 else 10]+=1
    details=(old[0],old[3],old[2],mission.category,grade,signed(mission.reward),
             (station,),descriptor(mission),updated[8] if grade==1 else 0,0,(0,),2,
             replacement if grade==0 else EMPTY,new_info,bonus_info,
             bonus[2] if bonus!=EMPTY else 0,group_info,group[2] if group!=EMPTY else 0)
    if extension and not (group[0]==14):raise WireError('Unexpected clue extension')
    messages=[BBQMessage(3,revision,tuple(updated),completion=details,tail=extension)]
    if grade==1:
        broadcast=list(details);broadcast[6]=(0,);broadcast[9]=1
        messages.append(BBQMessage(5,revision+1,None,completion=tuple(broadcast)))
    return tuple(messages)


class Planner:
    """Rotate catalogued variants; keep condition choices in observed ranges."""
    def __init__(self,catalog=None):
        self.catalog=catalog or Catalog();self.cursor={0:0,1:0,2:0}
        self.blue_slot=0

    def pick(self,grade,current_types=()):
        choices=self.catalog.automatic(grade)
        if grade==0:
            buckets={kind:sorted((m for m in choices if m.type==kind),key=lambda m:m.variation)
                     for kind in sorted({m.type for m in choices})}
            choices=tuple(bucket[index] for index in range(max(map(len,buckets.values())))
                          for bucket in buckets.values() if index<len(bucket))
        # Exercise the simpler group/photo families first; all allowed variants
        # remain present in the rotation, while sandwich is always excluded.
        if grade==2:
            buckets={kind:sorted((m for m in choices if m.type==kind),
                                key=lambda m:(m.difficulty,m.variation)) for kind in (25,3,15,14)}
            choices=tuple(bucket[index] for index in range(max(map(len,buckets.values())))
                          for bucket in buckets.values() if index<len(bucket))
        for _ in range(len(choices)):
            selected=choices[self.cursor[grade]%len(choices)];self.cursor[grade]+=1
            if selected.type not in current_types:break
        condition=1 if grade==0 and selected.type==33 else 2 if grade==2 and selected.type in (15,25) else 0
        return (selected.type,0.0,condition,selected.variation)

    def next(self,state,station,revision):
        # An existing gold sandwich remains in place; blue/red work may continue.
        index=6 if state[6][0] and state[6][0]!=5 else 5 if state[5][0] else 1+self.blue_slot%3
        replacement=bonus=group=EMPTY;extension=()
        if index in (1,2,3):
            self.blue_slot+=1
            replacement=self.pick(0,[q[0] for q in state[1:4]])
            if state[7]==9 and not state[5][0]:bonus=self.pick(1)
        elif index==5 and state[8]==2 and not state[6][0]:
            group=self.pick(2)
            if group[0]==14:
                # Neutral, game-observed clue target: species 603, type pair 4/5.
                # These are game data, not trainer/session data.
                group=(14,0.0,1,group[3])
                extension=(0,1,1,bytes.fromhex('5b0200000000000000000000'),
                           bytes.fromhex('0400000005000000ffffffffffffffff'),83,2)
        return completion_bundle(state,index,station,revision,replacement,bonus,group,
                                 extension,self.catalog)
