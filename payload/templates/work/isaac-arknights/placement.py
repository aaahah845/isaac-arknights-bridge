"""Resolve native attachment offsets on the same buffered timeline as owners."""


class Placements:
    def __init__(self,actors,position,scale):
        self.actors={(a.get('type'),a.get('id')):a for a in actors if not a.get('costume') and not a.get('part')}
        self.position=position;self.scale=scale;self.resolved={};self.visiting=set()

    def resolve(self,actor):
        key=actor.get('type'),actor.get('id')
        if key in self.resolved:return self.resolved[key]
        x,y=self.position(actor)
        if key in self.visiting:return x,y
        self.visiting.add(key)
        anchor=actor.get('attachment')
        if anchor:
            owner=self.actors.get((anchor['type'],anchor['id']))
            ox,oy=self.resolve(owner) if owner else (anchor['x'],anchor['y'])
            x=ox+anchor.get('localX',0)*self.scale+anchor.get('travelX',0)
            y=oy+anchor.get('localY',0)*self.scale+anchor.get('travelY',0)
        elif actor.get('spawnOffset'):
            x+=(self.scale-1)*actor['spawnOffset']['x']
            y+=(self.scale-1)*actor['spawnOffset']['y']
        self.visiting.remove(key);self.resolved[key]=(x,y)
        return x,y

    def actor(self,actor):
        x,y=self.resolve(actor);dx,dy=x-actor['x'],y-actor['y']
        result=dict(actor,x=x,y=y)
        if actor.get('beam'):
            result['beam']=[dict(sample,x=sample['x']+dx,y=sample['y']+dy) for sample in actor['beam']]
        return result
