"""Mission descriptors extracted from the local game's MissionInfos table."""
from dataclasses import dataclass
import json
import math
from pathlib import Path


DEFAULT_PATH=Path(__file__).resolve().parent/'data/mission_catalog.json'


@dataclass(frozen=True)
class Mission:
    category:int
    type:int
    variation:int
    goal:int
    reward:int
    reload:int
    release:int
    grade:int
    difficulty:int
    weight:float

    @property
    def key(self):
        return self.grade,self.type,self.variation

    @property
    def automatic_allowed(self):
        return not (self.grade==2 and self.type==5)

    def descriptor(self):
        return (self.category,self.type,self.variation,self.goal,self.reward,
                self.reload,self.release,self.grade,self.difficulty,float(self.weight))


class Catalog:
    def __init__(self,path=DEFAULT_PATH):
        rows=json.loads(Path(path).read_text(encoding='utf-8'))['entries']
        self.entries={}
        for row in rows:
            mission=Mission(**row)
            fields=mission.descriptor()
            if (any(type(value) is not int for value in fields[:-1])
                    or mission.grade not in (0,1,2) or mission.goal<=0
                    or mission.reward<0 or not math.isfinite(mission.weight)):
                raise ValueError('Invalid mission descriptor')
            if mission.key in self.entries:raise ValueError('Duplicate mission key')
            self.entries[mission.key]=mission

    def lookup(self,grade,quest):
        """Use variation as well as type: Ditto counts/rewards differ by variation."""
        kind,progress,condition,variation=quest
        try:return self.entries[grade,kind,variation]
        except KeyError as exc:raise ValueError('Unmapped mission variant') from exc

    def automatic(self,grade):
        return tuple(m for m in self.entries.values() if m.grade==grade and m.automatic_allowed)
