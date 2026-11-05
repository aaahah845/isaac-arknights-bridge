-- Arknights owns enemies; Isaac owns the player, items and their combinations.
-- Stopped callbacks remain inert so the local loader can reconnect on the
-- game's Lua thread without restarting the run.
local previous=ArkIsaacBridge
if previous then
 if previous.menuOwned and PauseMenu.GetState()==PauseMenuStates.OPEN then PauseMenu.SetState(PauseMenuStates.CLOSED) end
 for _,c in ipairs(ArkIsaacBridge.callbacks) do ArkIsaacBridge.mod:RemoveCallback(c[1],c[2]) end
 if ArkIsaacBridge.udp then ArkIsaacBridge.udp:close() end
end
local B={mod=RegisterMod('Isaac Arknights Bridge',1),callbacks={},proxies={},pending={},serial=0,frame=0,
 client=tostring(math.floor(os.clock()*1000000)),lastSeen=-1000,applying=false,textures={},imageSerial=0,deadIds={},kills=0,settled={},stateChunks={},operators={},textureAcks={}}
-- Reloading code preserves the live board and event numbers. Removing its
-- sentinel even for one update could trigger a native room-clear reward.
if previous then for _,key in ipairs({'proxies','pending','serial','frame','frameSequence','client','lastSeen','textures','imageSerial','deadIds','enemyLives','kills','settled','guard','roomEpoch','lastWalkable','state','input','oldInput','outcome','operators','textureAcks','textureQueue','textureTransfer','suspendedTextures','lastSeenAt','arenaRoom','arenaConfig','arenaTransfer','layoutVersion','lastLayout','terrainGrids','terrainRoom'}) do if previous[key]~=nil then B[key]=previous[key] end end end
ArkIsaacBridge=B
local json=require('json');local ok,socket=pcall(require,'socket');local game=Game()
-- Capture the old fitted coordinates before a render callback can overwrite
-- lastLayout with the new 40-unit layout during an in-place upgrade.
if previous and not previous.layoutVersion and previous.roomEpoch and B.state and B.state.width then
 local a,b=game:GetRoom():GetTopLeftPos(),game:GetRoom():GetBottomRightPos();local w,h=B.state.width,B.state.height
 local u=math.min((b.X-a.X-40)/w,(b.Y-a.Y-40)/h)
 B.migrationLayout=previous.lastLayout or {ox=a.X+(b.X-a.X-w*u)/2,oy=a.Y+(b.Y-a.Y-h*u)/2,u=u,w=w,h=h}
end
if B.mod:HasData() then local good,data=pcall(json.decode,B.mod:LoadData());if good and type(data)=='table' then B.settled=data.settled or {} end end
if ok then B.udp=socket.udp();B.udp:settimeout(0);B.udp:setpeername('127.0.0.1',18731) end
local function cb(id,fn,param)
 local wrapped=function(...) if not B.stopped then return fn(...) end end
 B.mod:AddCallback(id,wrapped,param);B.callbacks[#B.callbacks+1]={id,wrapped}
end
local function connected() return B.state and socket.gettime()-(B.lastSeenAt or 0)<2 end
local sendFrame
local function active() return connected() and B.state.active end
-- Input edges survive render/network resends until one native logic frame reads
-- them. Never replay held keys or old presses after focus/pause/session changes.
local function receiveInput(input)
 if not input then return end
 local permitted=B.state and B.state.active and not B.state.paused and input.focus and not input.isaacFocus
 local session=input.edgeSession or 'legacy';local baseline=B.inputSession~=session
 if not baseline and input.sequence and B.inputSequence and input.sequence<=B.inputSequence then return end
 B.inputSequence=input.sequence
 local old=B.input;B.inputSession=session;B.input=input;B.inputCounters=B.inputCounters or {};B.inputPending=B.inputPending or {}
 if baseline or not permitted then B.inputPending={};B.inputFrame={};B.inputFrameNumber=nil end
 for key,down in pairs(input) do if type(down)=='boolean' and key~='focus' and key~='isaacFocus' then
  local count=input.presses and input.presses[key]
  local pressed=count and count>(B.inputCounters[key] or count) or (not count and down and not (old and old[key]))
  if not baseline and permitted and pressed then B.inputPending[key]=socket.gettime() end
  if count then B.inputCounters[key]=count end
 end end
end
local function inputFrame()
 local frame=game:GetFrameCount()
 if B.inputFrameNumber~=frame then
  B.inputFrameNumber=frame;B.inputFrame={}
  for key,at in pairs(B.inputPending or {}) do if socket.gettime()-at<.2 then B.inputFrame[key]=true end end
  B.inputPending={}
 end
 return B.inputFrame or {}
end
B.receiveInput=receiveInput;B.readInputFrame=inputFrame
local function layout()
 local a,b=game:GetRoom():GetTopLeftPos(),game:GetRoom():GetBottomRightPos()
 local w,h=B.state.width or 11,B.state.height or 8;local u=40
 -- Keep the board on native grid boundaries. Never shrink a cell to fit.
 local ox=a.X+math.floor(((b.X-a.X)/u-w)/2)*u
 local oy=a.Y+math.floor(((b.Y-a.Y)/u-h)/2)*u
 B.lastLayout={ox=ox,oy=oy,u=u,w=w,h=h}
 return ox,oy,u
end
B.layout=layout
local function point(x,y) local ox,oy,u=layout();return Vector(ox+(x+.5)*u,oy+(B.state.height-y-.5)*u) end
local function coords(p) local ox,oy,u=layout();return (p.X-ox)/u-.5,B.state.height-.5-(p.Y-oy)/u end
local function renderTile() return Isaac.WorldToScreen(point(1,0)):Distance(Isaac.WorldToScreen(point(0,0))) end
-- WorldToScreen snaps short vectors to half pixels. Measure a long baseline.
local function worldScale() return Isaac.WorldToScreen(Vector(100,0)):Distance(Isaac.WorldToScreen(Vector.Zero))/100 end
local function followsOwner(f)
 local follower=f.IsFollower
 return (type(follower)=='function' and f:IsFollower() or follower==true) or (f.OrbitLayer or -1)>=0
end
local function ownerMount(source,depth)
 if not source or not source:Exists() or (depth or 0)>4 then return nil end
 if source.Type==1 then return Vector.Zero,source end
 if source.Type==3 then
  local f=source:ToFamiliar();local owner=f.Player
  if owner and owner:Exists() and followsOwner(f) then return source.Position-owner.Position,owner end
  return Vector.Zero,source
 end
 if source.Type==8 or source.Type==7 then
  local parent=source.Parent or source.SpawnerEntity;local mount,owner=ownerMount(parent,(depth or 0)+1)
  if mount then
   local travel=source.Type==8 and Vector.FromAngle(source:ToKnife().Rotation)*source:ToKnife():GetKnifeDistance() or Vector.Zero
   return mount+source.Position-parent.Position-travel,owner
  end
 end
end
local function rememberOrigin(e)
 local source=e.SpawnerEntity or e.Parent;local mount=ownerMount(source)
 if mount then
  local localOffset=e.Position-source.Position
  if e.Type==1000 and source.Type==7 then localOffset=Vector.Zero end
  local delta=mount+localOffset;e:GetData().arkSpawnOffset={x=delta.X,y=delta.Y}
 end
end
cb(ModCallbacks.MC_POST_TEAR_INIT,function(_,tear) rememberOrigin(tear) end)
cb(ModCallbacks.MC_POST_FIRE_TEAR,function(_,tear) rememberOrigin(tear) end)
cb(ModCallbacks.MC_POST_EFFECT_INIT,function(_,effect) rememberOrigin(effect) end)
B.teleport=function(x,y) Isaac.GetPlayer(0).Position=point(x,y);B.lastWalkable=point(x,y) end
local function passable(x,y,flying)
 if x<0 or y<0 or x>=B.state.width or y>=B.state.height then return false end
 if B.tileToken~=B.state.mapToken or B.tileSource~=B.state.tiles then
  B.tileToken=B.state.mapToken;B.tileSource=B.state.tiles;B.tilesByCell={}
  for _,t in ipairs(B.state.tiles or {}) do B.tilesByCell[t.y*B.state.width+t.x]=t end
 end
 local t=B.tilesByCell[y*B.state.width+x];if not t then return false end
 if flying then return t.flyable==true end
 return t.walkable==true
end
B.passable=passable
local function canStand(x,y,p)
 local _,_,u=layout();local multi=p.SizeMulti;local rx=math.max(.01,p.Size*multi.X/u);local ry=math.max(.01,p.Size*multi.Y/u)
 for ty=math.floor(y-ry+.5),math.floor(y+ry+.5) do for tx=math.floor(x-rx+.5),math.floor(x+rx+.5) do
  if not passable(tx,ty,p.CanFly) then
   local dx=math.max(0,math.abs(x-tx)-.5)/rx;local dy=math.max(0,math.abs(y-ty)-.5)/ry
   if dx*dx+dy*dy<1-.0001 then return false end
  end
 end end
 return true
end
B.canStand=canStand
local function pickupFits(x,y,p)
 local _,_,u=layout();local r=math.min(.4,math.max(.05,p.Size/u))
 for ty=math.floor(y-r+.5),math.floor(y+r+.5) do for tx=math.floor(x-r+.5),math.floor(x+r+.5) do
  if not passable(tx,ty,false) then
   local dx=math.max(0,math.abs(x-tx)-.5)/r;local dy=math.max(0,math.abs(y-ty)-.5)/r
   if dx*dx+dy*dy<1-.0001 then return false end
  end
 end end;return true
end
local function groundPickup(p)
 if not B.roomEpoch or not B.state or not B.state.tiles then return end
 local data=p:GetData();local x,y=coords(p.Position);local start=data.arkGroundPosition
 if data.arkGroundToken~=B.state.mapToken then start=nil end
 if start then local sx,sy=coords(start);if not pickupFits(sx,sy,p) then start=nil end end
 if not start and not pickupFits(x,y,p) then
  local best,distance=nil,math.huge
  for _,t in ipairs(B.state.tiles) do if pickupFits(t.x,t.y,p) then local d=(t.x-x)^2+(t.y-y)^2;if d<distance then best=t;distance=d end end end
  if best then p.Position=point(best.x,best.y);p.Velocity=Vector.Zero end
 elseif start then
  local _,_,u=layout();local delta=p.Position-start;local steps=math.max(1,math.ceil(delta:Length()/(u*.12)));local step=delta/steps;local accepted=start
  for i=1,steps do
   local candidate=accepted+step;local xx,yy=coords(candidate)
   if pickupFits(xx,yy,p) then accepted=candidate else
    local cx=Vector(candidate.X,accepted.Y);local ax,ay=coords(cx);if pickupFits(ax,ay,p) then accepted=cx end
    local cy=Vector(accepted.X,candidate.Y);ax,ay=coords(cy);if pickupFits(ax,ay,p) then accepted=cy end
   end
  end
  local velocity=p.Velocity;p.Velocity=Vector(math.abs(accepted.X-p.Position.X)>.01 and 0 or velocity.X,math.abs(accepted.Y-p.Position.Y)>.01 and 0 or velocity.Y);p.Position=accepted
 end
 data.arkGroundPosition=p.Position;data.arkGroundToken=B.state.mapToken
end
B.groundPickup=groundPickup;B.pickupFits=pickupFits
cb(ModCallbacks.MC_POST_PICKUP_INIT,function(_,p) groundPickup(p) end)
cb(ModCallbacks.MC_POST_PICKUP_UPDATE,function(_,p) groundPickup(p) end)
local function terrainRoomKey()
 local d=game:GetLevel():GetCurrentRoomDesc();return tostring(d.SafeGridIndex)..':'..tostring(d.DecorationSeed)
end
local function clearTerrain()
 if B.terrainRoom==terrainRoomKey() then
  local room=game:GetRoom();for index,kind in pairs(B.terrainGrids or {}) do local g=room:GetGridEntity(index)
   if g and g:GetType()==kind then room:RemoveGridEntity(index,0,false) end
  end
  room:Update()
 end
 B.terrainGrids={};B.terrainRoom=nil;B.terrainToken=nil;B.terrainVerifyAt=nil
end
local function syncTerrain(force)
 if not active() or not B.roomEpoch or B.arenaTransfer then return end
 local room=game:GetRoom();local key=terrainRoomKey()
 local changed=B.terrainRoom~=key or B.terrainToken~=B.state.mapToken
 if not force and not changed and (not B.terrainVerifyAt or B.frame<B.terrainVerifyAt) then return end
 B.terrainVerifyAt=nil
 local wanted={}
 for _,t in ipairs(B.state.tiles or {}) do
  -- Native indestructible low blocks have the original tear-height,
  -- spectral, bouncing, explosive-tear and bomb collision behaviour.
  if t.heightType==1 and t.tileKey~='tile_hole' then wanted[room:GetGridIndex(point(t.x,t.y))]=GridEntityType.GRID_ROCKB end
 end
 if B.terrainRoom~=key then B.terrainGrids={} end
 B.terrainGrids=B.terrainGrids or {}
 local removed=false
 for index,kind in pairs(B.terrainGrids) do if not wanted[index] then
  local g=room:GetGridEntity(index);if g and g:GetType()==kind then room:RemoveGridEntity(index,0,false);removed=true end
  B.terrainGrids[index]=nil
 end end
 for index,kind in pairs(wanted) do local g=room:GetGridEntity(index)
  if g and g:GetType()~=kind and g:GetType()~=GridEntityType.GRID_WALL and g:GetType()~=GridEntityType.GRID_DOOR then room:RemoveGridEntity(index,0,false);removed=true end
 end
 if removed then room:Update() end
 for index,kind in pairs(wanted) do
  local g=room:GetGridEntity(index)
  if not g then room:SpawnGridEntity(index,kind,0,991200+index,0);g=room:GetGridEntity(index) end
  if g and g:GetType()==kind then
   g:Update();g:GetSprite().Color=Color(1,1,1,0);B.terrainGrids[index]=kind
  end
 end
 if changed then B.terrainVerifyAt=B.frame+2 end
 B.terrainRoom=key;B.terrainToken=B.state.mapToken
end
B.syncTerrain=syncTerrain;B.clearTerrain=clearTerrain
cb(ModCallbacks.MC_PRE_GRID_ENTITY_ROCK_RENDER,function(_,g)
 if B.terrainGrids and B.terrainGrids[game:GetRoom():GetGridIndex(g.Position)] then return false end
end)
local artRoot='D:/IsaacArknights-Codex/client/mods/isaac_arknights_bridge/resources/gfx/ark_enemies/'
local mapSprite=Sprite();local pixelPath=artRoot..'pixel'
mapSprite:Load(pixelPath..'_v3.anm2',false);mapSprite:ReplaceSpritesheet(0,pixelPath..'.png');mapSprite:LoadGraphics();mapSprite:Play('Idle',true);B.mapSprite=mapSprite
local function skin(sprite,kind)
 local meta=B.state.skinMeta and B.state.skinMeta[kind];if not meta then return nil end
 local path=artRoot..meta.file;sprite:Load(path..'.anm2',false);sprite:ReplaceSpritesheet(0,path..'.png');sprite:LoadGraphics();sprite:Play('Idle',true)
 local scale=renderTile()/(meta.pixelsPerUnit or meta.width*.78);sprite.Scale=Vector(scale,scale);return meta.file
end
local function predicted(e)
 local age=(not B.state.paused and B.receivedAt) and math.min(.08,math.max(0,socket.gettime()-B.receivedAt)) or 0
 return point(e.x+(e.vx or 0)*age,e.y+(e.vy or 0)*age)
end
local function proxyGeometry(n,e)
 local _,_,u=layout()
 if e.colliderRadius and e.colliderRadius>0 then n.Size=math.max(1,e.colliderRadius*u) end
 local meta=B.state.skinMeta and B.state.skinMeta[e.kind]
 if meta then
  if n:GetData().skin~=meta.file then n:GetData().skin=skin(n:GetSprite(),e.kind) end
  local scale=renderTile()/(meta.pixelsPerUnit or meta.width*.78);n.SpriteScale=Vector(scale,scale)
 end
end
local function syncPausedProxies()
 -- The board can finish its last update after Isaac has already paused.
 -- Apply that final authoritative anchor without advancing Isaac physics.
 if not B.bridgePaused or not B.state then return end
 for _,e in ipairs(B.state.enemies or {}) do local n=B.proxies[e.id]
  if n and n:Exists() then n.Position=point(e.x,e.y);n.Velocity=Vector.Zero;proxyGeometry(n,e) end
 end
end
local function drawMap()
 if not active() or B.mapFrame==B.frame then return end;B.mapFrame=B.frame
 local u=renderTile();mapSprite.Scale=Vector((u-1)/2,(u-1)/2)
 for _,t in ipairs(B.state.tiles or {}) do
  local color=Color(.27,.35,.29,.95)
  if t.heightType==1 then color=Color(.46,.49,.52,.98) end
  if t.tileKey=='tile_forbidden' then color=Color(.12,.14,.16,1) elseif t.tileKey=='tile_hole' then color=Color(.025,.035,.045,1) elseif t.tileKey=='tile_start' then color=Color(.8,.15,.13,1) elseif t.tileKey=='tile_end' then color=Color(.1,.4,.85,1) end
  mapSprite.Color=color;mapSprite:Render(Isaac.WorldToScreen(point(t.x,t.y))-Vector(u/2,u/2))
 end
 B.operatorSprites=B.operatorSprites or {}
 for _,e in ipairs(B.state.characters or {}) do
  local meta=B.state.skinMeta and B.state.skinMeta[e.kind]
  if meta then
   local rec=B.operatorSprites[e.id];if not rec or rec.key~=meta.file then local sprite=Sprite();skin(sprite,e.kind);rec={sprite=sprite,key=meta.file};B.operatorSprites[e.id]=rec end
   local scale=u/(meta.pixelsPerUnit or meta.width*.78);rec.sprite.Scale=Vector(scale,scale)
   rec.sprite:Render(Isaac.WorldToScreen(predicted(e)))
  end
 end
end
cb(ModCallbacks.MC_PRE_NPC_RENDER,drawMap)
cb(ModCallbacks.MC_PRE_PLAYER_RENDER,drawMap)
local function cleanup() clearTerrain();for _,group in ipairs({B.proxies,B.operators}) do for _,e in pairs(group) do if e:Exists() then e:Remove() end end end;if B.guard and B.guard:Exists() then B.guard:Remove() end;B.guard=nil;B.proxies={};B.operators={};B.pending={};B.deadIds={};B.enemyLives={};B.kills=0;B.roomEpoch=nil;B.lastWalkable=nil end
B.cleanup=cleanup
local function ensureArena()
 if not active() or not B.state.width or B.arenaTransfer then return end
 local room=game:GetRoom();local a,b=room:GetTopLeftPos(),room:GetBottomRightPos()
 local w,h=B.state.width,B.state.height
 local shape=room:GetRoomShape();local rectangular=shape==RoomShape.ROOMSHAPE_1x1 or shape==RoomShape.ROOMSHAPE_1x2 or shape==RoomShape.ROOMSHAPE_2x1 or shape==RoomShape.ROOMSHAPE_2x2
 local fits=rectangular and b.X-a.X>=w*40 and b.Y-a.Y>=h*40
 if fits and B.layoutVersion==1 then return end
 -- Remember native entities rather than cloning pickups: seeds, prices,
 -- options groups and item RNG must survive the room transition unchanged.
 local old=B.migrationLayout or B.lastLayout
 if not old then
  local u=math.min((b.X-a.X-40)/w,(b.Y-a.Y-40)/h)
  old={ox=a.X+(b.X-a.X-w*u)/2,oy=a.Y+(b.Y-a.Y-h*u)/2,u=u,w=w,h=h}
 end
 local transfer={pickups={},old=old}
 local p=Isaac.GetPlayer(0);transfer.x=(p.Position.X-old.ox)/old.u-.5;transfer.y=old.h-.5-(p.Position.Y-old.oy)/old.u
 for _,e in ipairs(Isaac.GetRoomEntities()) do if e.Type==5 then
  transfer.pickups[#transfer.pickups+1]={entity=e,x=(e.Position.X-old.ox)/old.u-.5,y=old.h-.5-(e.Position.Y-old.oy)/old.u,persistent=e:HasEntityFlags(EntityFlag.FLAG_PERSISTENT)}
 end end
 if not fits then
  if w>26 or h>14 then B.arenaError='Map exceeds the native 2x2 room capacity';return end
  local level=game:GetLevel();local d=B.arenaRoom and level:GetRoomByIdx(B.arenaRoom)
  if not d or not d.Data or d.Data.Name~='Ark native grid arena' then
   B.arenaConfig=B.arenaConfig or RoomConfig.AddRooms(StbType.BASEMENT,-1,{{TYPE=1,VARIANT=957401,NAME='Ark native grid arena',SHAPE=RoomShape.ROOMSHAPE_2x2,WEIGHT=0,DIFFICULTY=1}})[1]
   d=nil
   for index=0,154 do if index%13<12 then d=level:TryPlaceRoom(B.arenaConfig,index,-1,991274,false,false,true);if d then break end end end
  end
  if not d then B.arenaError='No free 2x2 room on this floor';return end
  B.arenaRoom=d.SafeGridIndex;transfer.destination=B.arenaRoom
 end
 B.layoutVersion=1;B.arenaTransfer=transfer
 for _,record in ipairs(transfer.pickups) do record.entity:AddEntityFlags(EntityFlag.FLAG_PERSISTENT) end
 if transfer.destination then
  for _,group in ipairs({B.proxies,B.operators}) do for _,e in pairs(group) do if e:Exists() then e:Remove() end end end
  B.proxies={};B.operators={};if B.guard and B.guard:Exists() then B.guard:Remove() end;B.guard=nil
  room:SetClear(true);game:ChangeRoom(transfer.destination)
 end
 B.roomEpoch=nil;B.lastLayout=nil;B.warmupUpdates=1
end
local function finishArena()
 local transfer=B.arenaTransfer;if not transfer then return end
 if transfer.destination and game:GetLevel():GetCurrentRoomIndex()~=transfer.destination then return end
 B.teleport(transfer.x,transfer.y)
 for _,record in ipairs(transfer.pickups) do local e=record.entity
  if e:Exists() then
   e.Position=point(record.x,record.y);e.Velocity=Vector.Zero
   local data=e:GetData();data.arkGroundPosition=nil;data.arkGroundToken=nil;groundPickup(e:ToPickup())
   if not record.persistent then e:ClearEntityFlags(EntityFlag.FLAG_PERSISTENT) end
  end
 end
 B.arenaTransfer=nil;B.migrationLayout=nil;B.arenaError=nil;B.pickupCache={};B.poses=nil;B.visualPoseFrame=nil
end
B.ensureArena=ensureArena
local function reconcileLife(e)
 B.enemyLives=B.enemyLives or {}
 if e.life and B.enemyLives[e.id]~=e.life then
  local old=B.proxies[e.id];if old and old:Exists() then old:Remove() end
  B.proxies[e.id]=nil;B.deadIds[e.id]=nil;B.enemyLives[e.id]=e.life
 end
end
B.reconcileLife=reconcileLife
local function charge()
 local p=Isaac.GetPlayer(0)
 for _,slot in ipairs({ActiveSlot.SLOT_PRIMARY,ActiveSlot.SLOT_SECONDARY,ActiveSlot.SLOT_POCKET}) do
  local item=p:GetActiveItem(slot);local cfg=Isaac.GetItemConfig():GetCollectible(item)
  if cfg and cfg.MaxCharges>0 and cfg.ChargeType==0 then p:SetActiveCharge(math.min(cfg.MaxCharges,p:GetActiveCharge(slot)+1),slot) end
 end
end
local function settle(state)
 if not state.epoch or not state.gameResult or state.gameResult==0 then return end
 B.outcome=state.gameResult==1 and 'ARKNIGHTS VICTORY' or 'ARKNIGHTS DEFEAT'
 if B.settled[state.epoch] then return end
 B.settled[state.epoch]=true
 B.mod:SaveData(json.encode({settled=B.settled}))
 if state.gameResult==1 and game:GetNumPlayers()>0 then
  charge();local p=Isaac.GetPlayer(0);local rng=p:GetDropRNG()
  local variant=({PickupVariant.PICKUP_HEART,PickupVariant.PICKUP_COIN,PickupVariant.PICKUP_BOMB,PickupVariant.PICKUP_KEY})[rng:RandomInt(4)+1]
  Isaac.Spawn(EntityType.ENTITY_PICKUP,variant,0,p.Position+Vector(30,0),Vector.Zero,nil)
 end
end
local function guard()
 if B.guard and B.guard:Exists() and not B.guard:IsDead() then return end
 local n=Isaac.Spawn(EntityType.ENTITY_GAPER,0,0,Vector(-1000,-1000),Vector.Zero,nil):ToNPC();n:GetData().arkSentinel=true;n.Visible=false;n.Size=0;n.MaxHitPoints=1000000;n.HitPoints=1000000;n.EntityCollisionClass=EntityCollisionClass.ENTCOLL_NONE;n:AddEntityFlags(EntityFlag.FLAG_NO_TARGET|EntityFlag.FLAG_NO_REWARD|EntityFlag.FLAG_NO_STATUS_EFFECTS);B.guard=n
end
local function setupRoom()
 for _,e in ipairs(Isaac.GetRoomEntities()) do if e:IsEnemy() then e:Remove() end end
 local room=game:GetRoom()
 for i=0,room:GetGridSize()-1 do local g=room:GetGridEntity(i);if g and g:GetType()~=GridEntityType.GRID_DOOR and g:GetType()~=GridEntityType.GRID_WALL then room:RemoveGridEntity(i,0,false) end end
 guard();room:SetClear(false);room:Update()
 for i=0,7 do local d=room:GetDoor(i);if d then d:Close(true) end end
 local chosen=nil;local distance=math.huge
 for _,t in ipairs(B.state.tiles or {}) do if passable(t.x,t.y,Isaac.GetPlayer(0).CanFly) and t.tileKey~='tile_start' and t.tileKey~='tile_end' then
  local d=(t.x-B.state.width/2)^2+(t.y-B.state.height/2)^2;if d<distance then chosen=t;distance=d end
 end end
 B.teleport(chosen and chosen.x or 1,chosen and chosen.y or 1)
 guard();room:SetClear(false)
 B.terrainGrids={};B.terrainRoom=nil;B.terrainToken=nil;syncTerrain(true)
end
local function proxy(e)
 local npc=Isaac.Spawn(EntityType.ENTITY_GAPER,0,0,point(e.x,e.y),Vector.Zero,nil):ToNPC();npc:GetData().arkId=e.id;npc:GetData().arkLife=e.life
 npc:ClearEntityFlags(EntityFlag.FLAG_APPEAR)
 npc:AddEntityFlags(EntityFlag.FLAG_NO_KNOCKBACK|EntityFlag.FLAG_NO_PHYSICS_KNOCKBACK|EntityFlag.FLAG_NO_REWARD)
 npc.GridCollisionClass=EntityGridCollisionClass.GRIDCOLL_NONE;npc.EntityCollisionClass=EntityCollisionClass.ENTCOLL_ALL
 npc.MaxHitPoints=math.max(.01,e.maxHp/100);npc.HitPoints=math.max(.01,e.hp/100);B.proxies[e.id]=npc;return npc
end
local function ack(a)
 local h=B.pending[a.id];if not h then return end;B.pending[a.id]=nil;local npc=B.proxies[h.enemy]
 if h.life and B.enemyLives and B.enemyLives[h.enemy]~=h.life then return end
 if not npc or not npc:Exists() or not a.applied then return end
 local d=math.max(0,(a.before-a.after)/100)
 if a.after<=0 and not B.deadIds[h.enemy] then B.deadIds[h.enemy]=true;B.kills=B.kills+1;if B.kills%8==0 then charge() end end
 if d>0 then B.applying=true;npc.HitPoints=math.max(.01,a.before/100);npc:TakeDamage(d,h.flags,EntityRef(Isaac.GetPlayer(0)),h.countdown);if a.after>0 and npc:Exists() then npc.HitPoints=math.max(.01,a.after/100) end;B.applying=false end
end
local function poll()
 if not B.udp then return end
 local newest=nil;local drained,decoded,states=0,0,0
 local function consume(raw)
  decoded=decoded+1;local good,p=pcall(json.decode,raw)
  if not good or p.protocol~=1 then return end
  if p.input and not p.state then receiveInput(p.input) end
  if p.state then
   local old=B.state
   if old and old.epoch==p.state.epoch and old.mapToken==p.state.mapToken and not p.state.tiles then p.state.tiles=old.tiles end
   if old and old.skinToken==p.state.skinToken and not p.state.skinMeta then p.state.skinMeta=old.skinMeta;p.state.skins=old.skins end
   B.state=p.state;receiveInput(p.input);B.lastSeen=B.frame;B.lastSeenAt=socket.gettime();B.receivedAt=B.lastSeenAt
   if not B.state.active then for id,n in pairs(B.proxies) do if n:Exists() then n:Remove() end;B.proxies[id]=nil end end
   if old and old.epoch~=B.state.epoch then cleanup();B.outcome=nil end
   settle(B.state)
  end
  for _,a in ipairs(p.acks or {}) do ack(a) end
  for _,id in ipairs(p.textureAcks or {}) do B.textureAcks[id]=true end
 end
 -- Drain raw packets first. Decoding every obsolete full-map snapshot can
 -- otherwise take longer than the sender's interval and starve rendering.
 -- Receipt-only packets remain independent; pending hits are retransmitted.
 for _=1,512 do local raw=B.udp:receive(65507);if not raw then break end;drained=drained+1
  if raw:sub(1,4)=='IAST' and #raw>=16 then
   local session,seq,index,total=string.unpack('<I4I4I2I2',raw,5);local key=session..':'..seq
   if total>0 and total<=128 and index<total then
    local chunk=B.stateChunks[key] or {parts={},count=0,frame=B.frame,total=total};B.stateChunks[key]=chunk
    if not chunk.parts[index] then chunk.count=chunk.count+1;chunk.parts[index]=raw:sub(17) end
    if chunk.count==total then local parts={};for i=0,total-1 do parts[#parts+1]=chunk.parts[i] end;raw=table.concat(parts);B.stateChunks[key]=nil else raw='' end
   else raw='' end
  end
  if raw~='' then if raw:find('"state":',1,true) then newest=raw;states=states+1 else consume(raw) end end
 end
 if newest then consume(newest) end
 B.pollStats={drained=drained,decoded=decoded,states=states}
 B.coalescedStates=(B.coalescedStates or 0)+math.max(0,states-1)
 for key,chunk in pairs(B.stateChunks) do if B.frame-chunk.frame>120 then B.stateChunks[key]=nil end end
end
cb(ModCallbacks.MC_PRE_NPC_UPDATE,function(_,npc) if npc:GetData().arkId or npc:GetData().arkSentinel or npc:GetData().arkOperator then return true end end)
cb(ModCallbacks.MC_PRE_SPAWN_CLEAN_AWARD,function(_,rng) if B.roomEpoch then game:GetLevel():GetCurrentRoomDesc().AwardSeed=rng:GetSeed();return true end end)
cb(ModCallbacks.MC_POST_GAME_STARTED,function() B.restarting=false;B.warmupUpdates=90;cleanup() end)
cb(ModCallbacks.MC_POST_NEW_ROOM,function() if active() then B.roomEpoch=nil end end)
cb(ModCallbacks.MC_ENTITY_TAKE_DMG,function(_,e,amount,flags,source,countdown)
 if e:GetData().arkSentinel or e:GetData().arkOperator then return false end
 local id=e:GetData().arkId;if not id or B.applying then return end
 if source.Entity and source.Entity:GetData().arkAllyOwner==id then return false end
 if not active() or B.state.paused or amount<=0 or amount~=amount then return false end
 B.serial=B.serial+1;local key=B.client..':'..B.serial;local kind='physical'
 if (flags & DamageFlag.DAMAGE_LASER)~=0 or (flags & DamageFlag.DAMAGE_POISON_BURN)~=0 then kind='arts' end
 B.pending[key]={id=key,enemy=id,life=e:GetData().arkLife,epoch=B.state.epoch,amount=amount,kind=kind,flags=flags,countdown=countdown,created=B.frame};return false
end)
cb(ModCallbacks.MC_PRE_TEAR_COLLISION,function(_,tear,other)
 local owner=tear:GetData().arkAllyOwner;if owner and (other:GetData().arkId==owner or other:HasEntityFlags(EntityFlag.FLAG_CHARM)) then return true end
end)
local function weaponKey(projectile)
 if B.spawningWeapon then return B.spawningWeapon.projectileKey,B.spawningWeapon.atk end
 local source=projectile.SpawnerEntity;local id=source and source:GetData().arkId
 if id then for _,e in ipairs(B.state.enemies or {}) do if e.id==id then return e.projectileKey,e.atk end end end
end
cb(ModCallbacks.MC_POST_PROJECTILE_INIT,function(_,projectile)
 local key,atk=weaponKey(projectile);if key and key~='' then projectile:GetData().arkNativeShot=key;projectile.Visible=false;projectile.CollisionDamage=math.max(1,math.ceil((atk or 100)/200)) end
end)
cb(ModCallbacks.MC_POST_PROJECTILE_UPDATE,function(_,projectile)
 local data=projectile:GetData()
 if not data.arkNativeShot then local key,atk=weaponKey(projectile);if key and key~='' then data.arkNativeShot=key;projectile.CollisionDamage=math.max(1,math.ceil((atk or 100)/200)) end end
 if data.arkNativeShot then projectile.Visible=false end
end)
local function syncPause()
 -- Pause simulation only. The pause-menu state is a UI field, not a pause API.
 -- Rendering and networking must keep running while the native board is paused.
 B.bridgePaused=B.roomEpoch and (not connected() or B.state.paused or not B.state.active) and not B.restarting and (B.warmupUpdates or 0)<=0
end
cb(ModCallbacks.MC_PRE_UPDATE,function()
 poll();ensureArena();syncTerrain();syncPause();if sendFrame and socket.gettime()-(B.lastFrameSentAt or 0)>.1 then sendFrame() end
 if (B.warmupUpdates or 0)>0 then B.warmupUpdates=B.warmupUpdates-1 end
 if B.bridgePaused then B.inputPending={};B.inputFrame={};return true end
 inputFrame()
end)
cb(ModCallbacks.MC_POST_UPDATE,function()
 if not active() then return end
 if B.roomEpoch~=B.state.epoch then B.roomEpoch=B.state.epoch;setupRoom();finishArena() end
 local present={}
 local native={};for _,e in ipairs(B.state.enemies or {}) do native[e.id]=e end
 for _,e in ipairs(B.state.enemies or {}) do
  reconcileLife(e)
  if e.hp>0 and not B.deadIds[e.id] then
  present[e.id]=true;local n=B.proxies[e.id];if not n or not n:Exists() or n:IsDead() then n=proxy(e) end
  n.Position=predicted(e);n.Velocity=Vector.Zero;n.MaxHitPoints=math.max(.01,e.maxHp/100);n.HitPoints=math.max(.01,e.hp/100);n.Visible=not e.hidden
  proxyGeometry(n,e)
  for kind,flag in pairs({freeze=EntityFlag.FLAG_FREEZE,fear=EntityFlag.FLAG_FEAR,charm=EntityFlag.FLAG_CHARM,confusion=EntityFlag.FLAG_CONFUSION}) do if e.controlImmunes and e.controlImmunes[kind] then n:ClearEntityFlags(flag);if kind=='charm' then n:ClearEntityFlags(EntityFlag.FLAG_FRIENDLY) end end end
  if e.hidden then n:AddEntityFlags(EntityFlag.FLAG_NO_TARGET) else n:ClearEntityFlags(EntityFlag.FLAG_NO_TARGET) end
  local ally=n:HasEntityFlags(EntityFlag.FLAG_CHARM);local disabled=e.stunned or e.frozen or e.disarmed or n:HasEntityFlags(EntityFlag.FLAG_CONFUSION)
  n.CollisionDamage=(B.state.paused or ally or disabled or e.hidden) and 0 or math.max(1,math.ceil((e.atk or 100)/200))
  if not B.state.paused and not ally and not disabled and not e.hidden and (e.rangeRadius or 0)>1.2 and e.projectileKey and e.projectileKey~='' then
   local delta=Isaac.GetPlayer(0).Position-n.Position;local _,_,u=layout();local data=n:GetData();local tick=game:GetFrameCount()
   if delta:Length()<u*e.rangeRadius and tick>=(data.nextEnemyShot or 0) then
    B.spawningWeapon=e
    local good,error=pcall(function() n:FireProjectiles(n.Position,delta:Resized(5),0,ProjectileParams()) end)
    B.spawningWeapon=nil;if not good then Isaac.DebugString('BRIDGE PROJECTILE: '..tostring(error)) end
    data.nextEnemyShot=tick+math.max(10,math.floor((e.attackTime or 1)*30))
   end
  end
  -- Charmed routed enemies stay on their lane and attack the nearest foe.
  if not B.state.paused and n:HasEntityFlags(EntityFlag.FLAG_CHARM) then
   local data=n:GetData();local tick=game:GetFrameCount()
   if tick>=(data.nextAllyShot or 0) then
    local target,dist=nil,math.huge
    for id,other in pairs(B.proxies) do if id~=e.id and other:Exists() and not other:HasEntityFlags(EntityFlag.FLAG_CHARM) then local d=n.Position:Distance(other.Position);if d<dist then target=other;dist=d end end end
    local _,_,u=layout();if target and dist<u*2 then
     local tear=Isaac.GetPlayer(0):FireTear(n.Position,(target.Position-n.Position):Resized(7),false,true,false,n,1);tear.CollisionDamage=math.max(.01,(e.atk or 100)/100);tear:GetData().arkAllyOwner=e.id
     data.nextAllyShot=tick+math.max(10,math.floor((e.attackTime or 1)*30))
    end
   end
  end
  end
 end
 for id,n in pairs(B.proxies) do if not present[id] then if n:Exists() then n:Remove() end;B.proxies[id]=nil end end
 for id,n in pairs(B.operators) do if n:Exists() then n:Remove() end;B.operators[id]=nil end
 local p=Isaac.GetPlayer(0);local x,y=coords(p.Position);local cx,cy=math.max(0,math.min(B.state.width-1,x)),math.max(0,math.min(B.state.height-1,y));if x~=cx or y~=cy then p.Position=point(cx,cy);x=cx;y=cy end
 -- Use the runtime map's walking/flying rules, including dynamic obstacles.
 -- Sweep the centre between physics poses so speed items cannot skip a tile.
 local start=B.lastWalkable or p.Position;local destination=p.Position
 local sx,sy=coords(start)
 if not canStand(sx,sy,p) then
  local nearest,distance=nil,math.huge
  for _,t in ipairs(B.state.tiles or {}) do if canStand(t.x,t.y,p) then
   local d=(t.x-sx)^2+(t.y-sy)^2;if d<distance then nearest=t;distance=d end
  end end
  if nearest then start=point(nearest.x,nearest.y);destination=start end
 end
 local _,_,u=layout();local delta=destination-start;local steps=math.max(1,math.ceil(delta:Length()/(u*.12)));local step=delta/steps
 local accepted=start
 for i=1,steps do local candidate=accepted+step;local xx,yy=coords(candidate)
  if canStand(xx,yy,p) then accepted=candidate else
   -- Preserve the unblocked axis when moving diagonally along a wall.
   local cx=Vector(candidate.X,accepted.Y);local ax,ay=coords(cx)
   if canStand(ax,ay,p) then accepted=cx end
   local cy=Vector(accepted.X,candidate.Y);ax,ay=coords(cy)
   if canStand(ax,ay,p) then accepted=cy end
  end
 end
 if accepted:Distance(p.Position)>.01 then
  local velocity=p.Velocity
  p.Velocity=Vector(math.abs(accepted.X-p.Position.X)>.01 and 0 or velocity.X,math.abs(accepted.Y-p.Position.Y)>.01 and 0 or velocity.Y)
  p.Position=accepted
 end
 B.lastWalkable=p.Position
 guard()
end)
local actions={[ButtonAction.ACTION_LEFT]='left',[ButtonAction.ACTION_RIGHT]='right',[ButtonAction.ACTION_UP]='up',[ButtonAction.ACTION_DOWN]='down',[ButtonAction.ACTION_SHOOTLEFT]='shootLeft',[ButtonAction.ACTION_SHOOTRIGHT]='shootRight',[ButtonAction.ACTION_SHOOTUP]='shootUp',[ButtonAction.ACTION_SHOOTDOWN]='shootDown',[ButtonAction.ACTION_BOMB]='bomb',[ButtonAction.ACTION_ITEM]='item',[ButtonAction.ACTION_PILLCARD]='card',[ButtonAction.ACTION_DROP]='drop'}
cb(ModCallbacks.MC_POST_UPDATE,function()
 -- A pose timestamp belongs to one completed physics update, never to a resend.
 B.poseAt=socket.gettime();B.poseFrame=game:GetFrameCount();B.poses={}
 for _,e in ipairs(Isaac.GetRoomEntities()) do
  local pose={position=e.Position,velocity=e.Velocity}
  if e.Type==8 then local k=e:ToKnife();pose.knifeDistance=k:GetKnifeDistance();pose.knifeAngle=k.Rotation;pose.knifeSpriteRotation=e:GetSprite().Rotation end
  B.poses[e.InitSeed]=pose
 end
end)
cb(ModCallbacks.MC_INPUT_ACTION,function(_,entity,hook,action)
 if not entity or entity.Type~=EntityType.ENTITY_PLAYER then return end
 if not active() or not B.input or B.input.isaacFocus then return end;local key=actions[action];if not key then return end
 local triggered=B.input.focus and inputFrame()[key] or false
 local pulse=(key=='item' or key=='card' or key=='bomb') and triggered
 local down=B.input.focus and (B.input[key] or pulse) or false
 if hook==InputHook.GET_ACTION_VALUE then return down and 1 or 0 elseif hook==InputHook.IS_ACTION_PRESSED then return down elseif hook==InputHook.IS_ACTION_TRIGGERED then return triggered end
end)
local function internLayer(d)
 B.layerIntern=B.layerIntern or {};B.layerIds=B.layerIds or {}
 local values={d.image,d.name,d.w,d.h,d.sourceX,d.sourceY,d.px,d.py,d.x,d.y,d.sx,d.sy,d.rotation,d.flipX and 1 or 0,d.flipY and 1 or 0}
 for _,v in ipairs(d.color) do values[#values+1]=v end;for _,v in ipairs(d.colorize) do values[#values+1]=v end
 local key=table.concat(values,':');local old=B.layerIntern[key];if old then return old end
 B.layerSerial=(B.layerSerial or 0)+1;B.layerIds[d]=B.layerSerial;B.layerIntern[key]=d;B.layerInternCount=(B.layerInternCount or 0)+1;return d
end
local function layers(sprite,allow,hide,body)
 local out={}
 for _,l in ipairs(sprite:GetAllLayers()) do
  local id=l:GetLayerID();local source=body or sprite;local f
  if body then l=body:GetLayer(id);f=body:GetLayerFrameData(id)
  else f=sprite:GetOverlayLayerFrameData(id);if not f or not f:IsVisible() then f=sprite:GetLayerFrameData(id) end end
  if f and f:IsVisible() and l:IsVisible() and (not allow or allow[id]) and (not hide or not hide[id]) then
   local c=f:GetCrop();local w,h=math.floor(f:GetWidth()),math.floor(f:GetHeight());local image=l:GetSpritesheet()
   if image and w>0 and h>0 and w<=512 and h<=512 then
    local iw,ih=image:GetWidth(),image:GetHeight();local atlas=iw>0 and ih>0 and iw<=512 and ih<=512
    local key=l:GetSpritesheetPath()..(atlas and ':atlas:'..iw..':'..ih or ':'..c.X..':'..c.Y..':'..w..':'..h);local rec=B.textures[key]
    if not rec then B.imageSerial=B.imageSerial+1;rec={id=B.imageSerial,last=-10000};B.textures[key]=rec end
    if rec.queued then rec.priority=math.min(rec.priority or 2,B.texturePriority or 2) end
    if not B.textureAcks[rec.id] and not rec.queued and socket.gettime()-(rec.lastSentAt or -1000)>2 then
     B.textureQueue=B.textureQueue or {};rec.queued=true;rec.image=image;rec.x=atlas and 0 or math.floor(c.X);rec.y=atlas and 0 or math.floor(c.Y);rec.w=atlas and iw or w;rec.h=atlas and ih or h;rec.priority=B.texturePriority or 2
     B.textureQueue[#B.textureQueue+1]=rec
    end
    local pivot,pos,s=f:GetPivot(),f:GetPos(),f:GetScale();local col=f:GetColor()*l:GetColor()*source.Color
    local colorize=col:GetColorize();local extra,size=l:GetPos(),l:GetSize()
    out[#out+1]=internLayer({image=rec.id,name=l:GetName(),w=w,h=h,sourceX=atlas and c.X or 0,sourceY=atlas and c.Y or 0,px=pivot.X,py=pivot.Y,x=pos.X+extra.X,y=pos.Y+extra.Y,sx=s.X*size.X,sy=s.Y*size.Y,rotation=f:GetRotation()+l:GetRotation(),flipX=l:GetFlipX(),flipY=l:GetFlipY(),color={col.R,col.G,col.B,col.A,col.RO,col.GO,col.BO},colorize={colorize.R,colorize.G,colorize.B,colorize.A}})
   end
  end
 end;return out
end
local function flushTextures()
 B.textureReadsThisFrame=0
 if not B.udp then return end
 B.suspendedTextures=B.suspendedTextures or {}
 local waiting=B.textureQueue or {};local top=nil
 for _,rec in ipairs(waiting) do if not top or rec.priority<top then top=rec.priority end end
 if B.textureTransfer and top and top<B.textureTransfer.rec.priority then
  B.suspendedTextures[#B.suspendedTextures+1]=B.textureTransfer;B.textureTransfer=nil
 end
 if not B.textureTransfer and #B.suspendedTextures>0 then
  local best=1;for i=2,#B.suspendedTextures do if B.suspendedTextures[i].rec.priority<B.suspendedTextures[best].rec.priority then best=i end end
  if not top or B.suspendedTextures[best].rec.priority<=top then B.textureTransfer=table.remove(B.suspendedTextures,best) end
 end
 if not B.textureTransfer and B.textureQueue and #B.textureQueue>0 then
  local index=1;for i=2,#B.textureQueue do if B.textureQueue[i].priority<B.textureQueue[index].priority then index=i end end
  local rec=table.remove(B.textureQueue,index)
  if B.textureAcks[rec.id] then rec.queued=false;rec.image=nil else
   local started=socket.gettime();B.textureReadsThisFrame=1;B.textureTotalReads=(B.textureTotalReads or 0)+1
   local good,pixels=pcall(function() return rec.image:GetTexelRegion(rec.x,rec.y,rec.w,rec.h) end)
   B.textureReadMs=(socket.gettime()-started)*1000
   if good and #pixels==rec.w*rec.h*4 then B.textureTransfer={rec=rec,pixels=pixels,index=0,total=math.ceil(#pixels/8000)}
   else rec.queued=false;rec.lastSentAt=socket.gettime();B.textureError=good and 'Unexpected texture byte count' or tostring(pixels) end
   rec.image=nil
  end
 end
 -- One GPU read and at most 96 KB of texture traffic per render frame.
 local transfer=B.textureTransfer
 if transfer then
  for _=1,12 do
   local i=transfer.index;local rec=transfer.rec
   B.udp:send('IAIM'..string.pack('<I4I2I2I2I2',rec.id,rec.w,rec.h,i,transfer.total)..transfer.pixels:sub(i*8000+1,(i+1)*8000))
   transfer.index=i+1
   if transfer.index>=transfer.total then rec.queued=false;rec.lastSentAt=socket.gettime();B.textureTransfer=nil;break end
  end
 end
end
local function visuals()
 local out={};local projectionScale=worldScale();local ox,oy,u=layout();B.layerIntern=B.layerIntern or {};B.layerIds=B.layerIds or {};B.layerSerial=B.layerSerial or 0;B.styleKeys=B.styleKeys or setmetatable({},{__mode='k'})
 if (B.layerInternCount or 0)>4096 then B.layerIntern={};B.layerIds={};B.layerSerial=0;B.layerInternCount=0;B.styleKeys=setmetatable({},{__mode='k'});B.pickupCache={} end
 B.pickupCache=B.pickupCache or {};local presentPickups={};local now=socket.gettime()
 local function mapcoords(p) return (p.X-ox)/u-.5,B.state.height-.5-(p.Y-oy)/u end
 for _,e in ipairs(Isaac.GetRoomEntities()) do
  if not e:GetData().arkId and not e:GetData().arkOperator and (e.Visible or e:GetData().arkNativeShot) and (e.Type==1 or e.Type==2 or e.Type==3 or e.Type==4 or e.Type==5 or e.Type==7 or e.Type==8 or e.Type==9 or e.Type==1000) then
   local pose=B.poses and B.poses[e.InitSeed];local position=pose and pose.position or e.Position;local velocity=pose and pose.velocity or e.Velocity
   local x,y=mapcoords(position)
   local cosmetic=e.Type==1000 and (e.Variant==EffectVariant.BLOOD_DROP or e.Variant==EffectVariant.WATER_SPLASH or e.Variant==EffectVariant.WALL_BUG)
   local cacheable=e.Type==5 or cosmetic;local cached=cacheable and B.pickupCache[e.InitSeed]
   if cacheable then presentPickups[e.InitSeed]=true end
   if cached and now-cached.at<.1 and cached.variant==e.Variant and cached.subtype==e.SubType then
    -- Pickups keep full-rate geometry; their decorative sprite frame can be
    -- reused briefly instead of repeating all native layer calls per coin.
    local actor={};for k,v in pairs(cached.actor) do actor[k]=v end
    local sprite=e:GetSprite();local offset=e.SpriteOffset+sprite.Offset;local render=e.PositionOffset
    actor.x=x;actor.y=y;actor.vx=velocity.X*30/u;actor.vy=-velocity.Y*30/u;actor.rotation=sprite.Rotation
    actor.height=offset.Y+render.Y*projectionScale;actor.offsetX=offset.X+render.X*projectionScale;actor.renderDepth=position.Y+e.DepthOffset+e.RenderZOffset
    actor.scaleX=sprite.Scale.X;actor.scaleY=sprite.Scale.Y
    if actor.scaleX==cached.actor.scaleX and actor.scaleY==cached.actor.scaleY then B.styleKeys[actor]=B.styleKeys[cached.actor] end
    out[#out+1]=actor
   else
   local hide,allowed={},{}
   if e.Type==1 and not e:ToPlayer():IsFullSpriteRendering() then local good,map=pcall(function() return e:ToPlayer():GetCostumeLayerMap() end);if good then for slot,entry in ipairs(map) do if entry.costumeIndex and entry.costumeIndex>=0 then hide[slot-1]=true;allowed[entry.costumeIndex]=allowed[entry.costumeIndex] or {};allowed[entry.costumeIndex][entry.layerID]=true end end end end
   B.texturePriority=e.Type==1 and -2 or ((e.Type==2 or e.Type==7 or e.Type==8 or e.Type==9) and 1 or 2)
   local sprite=e:GetSprite();local body=nil
   if e.Type==1 and e:ToPlayer():IsFullSpriteRendering() then body=e:ToPlayer():GetBodySprite();if body:GetFilename()=='' then body=nil end end
   local good,ls=true,{};if not e:GetData().arkNativeShot then good,ls=pcall(layers,sprite,nil,hide,body) end
   if good then
    local rs=body or sprite
    local actor={id=e.InitSeed,type=e.Type,x=x,y=y,vx=velocity.X*30/u,vy=-velocity.Y*30/u,layers=ls,scale=e.SpriteScale.X,scaleX=rs.Scale.X,scaleY=rs.Scale.Y,flipX=rs.FlipX,flipY=rs.FlipY,rotation=rs.Rotation,height=e.SpriteOffset.Y+rs.Offset.Y,offsetX=e.SpriteOffset.X+rs.Offset.X,size=e.Size,animation=rs:GetAnimation(),animationFrame=rs:GetFrame(),renderDepth=position.Y+e.DepthOffset+e.RenderZOffset}
    local source=e.SpawnerEntity;local parent=e.Parent
    if e.Type==8 and pose then actor.rotation=pose.knifeSpriteRotation end
    actor.playerMounted=(e.Type==2 or e.Type==7 or e.Type==8) and ((source and source:Exists() and source.Type==1) or (parent and parent:Exists() and parent.Type==1)) or false
    if e.Type==1000 and parent and parent:Exists() and parent.Type==EntityType.ENTITY_LASER then
     local owner=parent.Parent or parent.SpawnerEntity;actor.playerMounted=owner and owner:Exists() and owner.Type==1 or false
    end
    if e.Type~=EntityType.ENTITY_PLAYER and not e:GetData().arkNativeShot then
     local renderOffset=e.PositionOffset;actor.offsetX=actor.offsetX+renderOffset.X*projectionScale;actor.height=actor.height+renderOffset.Y*projectionScale
    end
    if e.Type==EntityType.ENTITY_PLAYER then local flying=e:ToPlayer():GetFlyingOffset();actor.height=actor.height+flying.Y*worldScale();actor.offsetX=actor.offsetX+flying.X*worldScale() end
    if e:GetData().arkNativeShot then actor.nativeWeapon=e:GetData().arkNativeShot;actor.layers={};actor.height=e:ToProjectile().Height+e.SpriteOffset.Y end
    local origin=e:GetData().arkSpawnOffset
    if origin then actor.spawnOffset={x=origin.x/u,y=-origin.y/u} end
    local attachParent=nil;local travel=Vector.Zero
    if e.Type==8 and parent and parent:Exists() and ownerMount(parent) then
     local knife=e:ToKnife();attachParent=parent;travel=Vector.FromAngle(pose and pose.knifeAngle or knife.Rotation)*(pose and pose.knifeDistance or knife:GetKnifeDistance())
    elseif e.Type==7 and parent and parent:Exists() and ownerMount(parent) then attachParent=parent
    elseif e.Type==3 then local f=e:ToFamiliar();if followsOwner(f) then attachParent=f.Player end end
    if attachParent and attachParent:Exists() then
     local pp=B.poses and B.poses[attachParent.InitSeed];local parentPosition=pp and pp.position or attachParent.Position
     local px,py=mapcoords(parentPosition);local relative=position-parentPosition-travel
     actor.attachment={id=attachParent.InitSeed,type=attachParent.Type,x=px,y=py,localX=relative.X/u,localY=-relative.Y/u,travelX=travel.X/u,travelY=-travel.Y/u}
    end
    if e.Type==EntityType.ENTITY_LASER then
     local laser=e:ToLaser();local points={};local samples=laser:GetNonOptimizedSamples();local distance=0;local last=nil
     if #samples>0 then
      local indices={};for i=0,#samples-1,math.max(1,math.ceil(#samples/64)) do indices[#indices+1]=i end
      if indices[#indices]~=#samples-1 then indices[#indices+1]=#samples-1 end
      for _,i in ipairs(indices) do local p=samples:Get(i);if last then distance=distance+p:Distance(last) end;local xx,yy=mapcoords(p);points[#points+1]={x=xx,y=yy,d=distance};last=p end
     else local p=laser:GetEndPoint();local xx,yy=mapcoords(p);points={{x=x,y=y,d=0},{x=xx,y=yy,d=p:Distance(position)}} end
     actor.beam=points;actor.beamWorldUnitsPerTile=u;actor.beamPixelScale=projectionScale;actor.laserVariant=e.Variant;actor.beamClosed=#points>2 and math.abs(points[1].x-points[#points].x)+math.abs(points[1].y-points[#points].y)<.1
     actor.beamLayers=ls;actor.layers={}
    end
    out[#out+1]=actor
    if cacheable then B.pickupCache[e.InitSeed]={actor=actor,at=now,variant=e.Variant,subtype=e.SubType} end
   end
   if e.Type==1 then local good,descs=pcall(function() return e:ToPlayer():GetCostumeSpriteDescs() end)
    if good then for index,desc in ipairs(descs) do if allowed[index-1] then local cs=desc:GetSprite();local good,ls=pcall(function() return layers(cs,allowed[index-1]) end);if good and #ls>0 then local flying=e:ToPlayer():GetFlyingOffset();out[#out+1]={id=e.InitSeed,type=1,x=x,y=y,layers=ls,scale=e.SpriteScale.X,scaleX=e.SpriteScale.X,scaleY=e.SpriteScale.Y,rotation=cs.Rotation,height=e.SpriteOffset.Y+flying.Y*worldScale()+cs.Offset.Y,offsetX=e.SpriteOffset.X+flying.X*worldScale()+cs.Offset.X,costume=true,costumeIndex=index,renderDepth=position.Y+e.DepthOffset+e.RenderZOffset} end end end end
    local player=e:ToPlayer()
    if player:IsHeldItemVisible() then
     B.texturePriority=-2;local held=player:GetHeldSprite();local hidden={}
     if body and body:GetAnimation():sub(1,3)=='Use' then for _,l in ipairs(held:GetAllLayers()) do if l:GetName():lower()=='sparkle' then hidden[l:GetLayerID()]=true end end end
     local good,ls=pcall(layers,held,nil,hidden)
     if good and #ls>0 then local flying=player:GetFlyingOffset();out[#out+1]={id=e.InitSeed,type=1,x=x,y=y,layers=ls,part='held',scaleX=held.Scale.X,scaleY=held.Scale.Y,rotation=held.Rotation,height=e.SpriteOffset.Y+flying.Y*worldScale()+held.Offset.Y,offsetX=e.SpriteOffset.X+flying.X*worldScale()+held.Offset.X,animation=held:GetAnimation(),animationFrame=held:GetFrame(),renderOrder=2,renderDepth=position.Y+e.DepthOffset+e.RenderZOffset} end
    end
   end
   end
  end
 end
 for id in pairs(B.pickupCache) do if not presentPickups[id] then B.pickupCache[id]=nil end end
 for i=0,game:GetRoom():GetGridSize()-1 do local g=game:GetRoom():GetGridEntity(i)
  if g and not (B.terrainGrids and B.terrainGrids[i]) and g:GetType()~=GridEntityType.GRID_WALL and g:GetType()~=GridEntityType.GRID_DOOR then
   local good,ls=pcall(layers,g:GetSprite());if good and #ls>0 then local x,y=coords(g.Position);out[#out+1]={id=10000000+i,type='grid',x=x,y=y,layers=ls,scale=1,rotation=0,height=0} end
  end
 end;return out
end
local styleFields={'type','scale','scaleX','scaleY','flipX','flipY','size','animation','animationFrame','renderOrder','costume','costumeIndex','part','playerMounted','nativeWeapon','laserVariant','beamClosed'}
local styleSet={layers=true,beamLayers=true};for _,key in ipairs(styleFields) do styleSet[key]=true end
local function packActors(actors)
 local wire,styles,known={},{},{};B.layerIds=B.layerIds or {};B.styleKeys=B.styleKeys or setmetatable({},{__mode='k'})
 for _,a in ipairs(actors) do
  local key=B.styleKeys[a]
  if not key then
  local keys={};for _,key in ipairs(styleFields) do local value=a[key];keys[#keys+1]=type(value)..':'..tostring(value) end
  for _,field in ipairs({'layers','beamLayers'}) do
   keys[#keys+1]=field
   for _,layer in ipairs(a[field] or {}) do
    if not B.layerIds[layer] then B.layerSerial=(B.layerSerial or 0)+1;B.layerIds[layer]=B.layerSerial end
    keys[#keys+1]=tostring(B.layerIds[layer])
   end
  end
  key=table.concat(keys,'|');B.styleKeys[a]=key
  end
  local id=known[key]
  if not id then
   local style={};for k,v in pairs(a) do if styleSet[k] then style[k]=v end end
   styles[#styles+1]=style;id=#styles;known[key]=id
  end
  local item={s=id};for k,v in pairs(a) do if not styleSet[k] then item[k]=v end end;wire[#wire+1]=item
 end;return wire,styles
end
B.packActors=packActors
local function screenEffects()
 local out={};local s=ItemOverlay.GetSprite();local anim=s:GetAnimation()
 if ItemOverlay.GetOverlayID()>0 and ItemOverlay.GetDelay()<=0 and anim~='' and not s:IsFinished(anim) then
  B.texturePriority=-1;local good,ls=pcall(layers,s)
  if good and #ls>0 then out[1]={layers=ls,scaleX=s.Scale.X,scaleY=s.Scale.Y,offsetX=s.Offset.X,offsetY=s.Offset.Y,rotation=s.Rotation,animation=anim,frame=s:GetFrame(),id=ItemOverlay.GetOverlayID()} end
 end
 return out
end
local function hudPicture(key,path,anim,frame,graphic)
 B.hudSprites=B.hudSprites or {};local s=B.hudSprites[key]
 if not s then
  s=Sprite();s:Load(path,true)
  if graphic then s:ReplaceSpritesheet(1,graphic);s:LoadGraphics() end
  B.hudSprites[key]=s
 end
 s:SetFrame(anim,frame or 0)
 return layers(s,graphic and {[1]=true} or nil)
end
local function hudFrame(p)
 local out={icons={},hearts={},actives={}}
 B.texturePriority=-3
 out.font=hudPicture('hudfont','gfx/005.100_collectible.anm2','Idle',0,'font/pftempestasevencondensed_0.png')
 out.chargeEmpty=hudPicture('charge-empty','gfx/ui/ui_chargebar.anm2','BarEmpty')
 out.chargeFull=hudPicture('charge-full','gfx/ui/ui_chargebar.anm2','BarFull')
 out.chargeDividers={}
 for _,n in ipairs({1,2,3,4,5,6,8,12}) do out.chargeDividers[tostring(n)]=hudPicture('charge-dividers'..n,'gfx/ui/ui_chargebar.anm2','BarOverlay'..n) end
 out.pickups={}
 for _,i in ipairs({0,2,1}) do out.pickups[#out.pickups+1]=hudPicture('pickup-icon'..i,'gfx/ui/hudpickups.anm2','Idle',i) end
 for i=0,5 do out.icons[#out.icons+1]=hudPicture('stat'..i,'gfx/ui/hudstats2.anm2','Idle',i) end
 for _,heart in ipairs(game:GetHUD():GetPlayerHUD(0):GetHearts()) do
  if heart:IsVisible() then
   local anim=heart:GetHeartAnim();local picture={layers=hudPicture('heart:'..anim,'gfx/ui/ui_hearts.anm2',anim)}
   if heart:IsGoldenHeartOverlayVisible() then picture.gold=hudPicture('heart:gold','gfx/ui/ui_hearts.anm2','GoldHeartOverlay') end
   if heart:IsEternalHeartOverlayVisible() then picture.eternal=hudPicture('heart:eternal','gfx/ui/ui_hearts.anm2','WhiteHeartOverlay') end
   out.hearts[#out.hearts+1]=picture
  end
 end
 for slot=0,3 do
  local id=p:GetActiveItem(slot);local config=Isaac.GetItemConfig():GetCollectible(id)
  if id>0 and config then out.actives[#out.actives+1]={slot=slot,id=id,charge=p:GetActiveCharge(slot),battery=p:GetBatteryCharge(slot),
   maxCharge=config.MaxCharges,chargeType=config.ChargeType,layers=hudPicture('active:'..id,'gfx/005.100_collectible.anm2','Idle',0,config.GfxFileName)} end
 end
 return out
end
local function buildFrame(rendering)
 local sendAt=socket.gettime()
 if rendering then local good,effects=pcall(screenEffects);if good then B.screenEffects=effects else B.screenEffectError=tostring(effects) end end
 if rendering and game:GetNumPlayers()>0 and sendAt-(B.lastHudAt or 0)>.1 then
  local good,hud=pcall(hudFrame,Isaac.GetPlayer(0));B.lastHudAt=sendAt
  if good then B.hud=hud;B.hudError=nil else B.hudError=tostring(hud) end
 end
 -- Render-context pictures keep the timestamp of the physics pose they show.
 local animationKey=''
 if rendering and game:GetNumPlayers()>0 then
  local p=Isaac.GetPlayer(0)
  if p:IsFullSpriteRendering() or p:IsHeldItemVisible() then local body=p:GetBodySprite();local held=p:GetHeldSprite();animationKey=table.concat({tostring(p:IsFullSpriteRendering()),body:GetAnimation(),body:GetFrame(),tostring(p:IsHeldItemVisible()),held:GetAnimation(),held:GetFrame()},':') end
 end
 if rendering and B.state and B.state.width and (B.visualPoseFrame~=B.poseFrame or animationKey~=B.lastAnimationKey or sendAt-(B.lastVisualAt or 0)>.1) then
  local started=socket.gettime();local good,actors=pcall(visuals)
  B.visualMs=(socket.gettime()-started)*1000
  if good then B.cachedActors=actors;B.wireActors,B.wireStyles=packActors(actors);B.visualError=nil;B.visualPoseAt=B.poseAt or sendAt;B.visualPoseFrame=B.poseFrame;B.visualRevision=(B.visualRevision or 0)+1;B.lastAnimationKey=animationKey
  else B.visualError=tostring(actors);Isaac.DebugString(B.visualError) end
  B.lastVisualAt=sendAt
 end
 if B.udp and sendAt-(B.lastFrameSentAt or 0)>=1/60 then
  B.lastFrameSentAt=sendAt
  local hits={};for key,h in pairs(B.pending) do if B.frame-h.created<300 then hits[#hits+1]=h else B.pending[key]=nil end end
  local packet={protocol=1,type='frame',client=B.client,frame=B.frame,mapEpoch=B.state and B.state.tiles and B.state.epoch,mapToken=B.state and B.state.tiles and B.state.mapToken,skinToken=B.state and B.state.skinMeta and B.state.skinToken,gameFrame=B.poseFrame or game:GetFrameCount(),poseAt=B.poseAt or sendAt,sentAt=sendAt,hits=hits,rgon=REPENTOGON~=nil,paused=game:IsPaused() or not not B.bridgePaused,menuPaused=PauseMenu.GetState()~=0,statuses={},renderTiming=B.renderTiming}
  for id,n in pairs(B.proxies) do if n:Exists() and not n:IsDead() then
   local kinds={};for kind,flag in pairs({slow=EntityFlag.FLAG_SLOW,freeze=EntityFlag.FLAG_FREEZE,fear=EntityFlag.FLAG_FEAR,charm=EntityFlag.FLAG_CHARM,confusion=EntityFlag.FLAG_CONFUSION}) do if n:HasEntityFlags(flag) then kinds[#kinds+1]=kind end end
   if #kinds>0 then packet.statuses[#packet.statuses+1]={enemy=id,kinds=kinds} end
  end end
  if game:GetNumPlayers()>0 and B.state and B.state.width then
   local p=Isaac.GetPlayer(0);local x,y=coords(p.Position);local _,_,u=layout();packet.pixelsPerTile=u;packet.spritePixelsPerTile=renderTile()
   packet.player={x=x,y=y,damage=p.Damage,fireDelay=p.MaxFireDelay,speed=p.MoveSpeed,range=p.TearRange,shotSpeed=p.ShotSpeed,luck=p.Luck,hearts=p:GetHearts(),soulHearts=p:GetSoulHearts(),coins=p:GetNumCoins(),bombs=p:GetNumBombs(),keys=p:GetNumKeys(),dead=p:IsDead()}
   packet.hud=B.hud;packet.hudError=B.hudError
   -- Reading texture pixels requires the render context. Input and update
   -- callbacks only resend the last completed picture; they never read GL.
   packet.entities=B.wireActors or B.cachedActors or {};packet.entityStyles=B.wireStyles;packet.visualError=B.visualError;packet.visualPoseAt=B.visualPoseAt;packet.visualPoseFrame=B.visualPoseFrame;packet.visualRevision=B.visualRevision
   packet.screenEffects=B.screenEffects or {};packet.screenEffectError=B.screenEffectError;packet.screenSize={Isaac.GetScreenWidth(),Isaac.GetScreenHeight()}
   packet.roomProjection={};for _,cell in ipairs({{-.5,-.5},{B.state.width-.5,-.5},{B.state.width-.5,B.state.height-.5},{-.5,B.state.height-.5}}) do local q=Isaac.WorldToScreen(point(cell[1],cell[2]));packet.roomProjection[#packet.roomProjection+1]={x=q.X,y=q.Y} end
  end
  -- Gameplay events must survive large visual frames; trim pictures first.
  -- Damage batches use separate datagrams so visual volume cannot drop hits.
  for i=1,#hits,80 do local batch={};for j=i,math.min(i+79,#hits) do batch[#batch+1]=hits[j] end;B.udp:send(json.encode({protocol=1,type='hits',client=B.client,epoch=B.state and B.state.epoch,hits=batch})) end
  -- Physics is 30 Hz. Re-sending the identical large actor tree at 60 Hz
  -- wastes Lua JSON time; compact references keep the last complete picture.
  if B.visualRevision and B.visualRevision==B.sentVisualRevision and sendAt-(B.lastFullVisualAt or 0)<.1 then
   packet.visualReference=B.visualRevision;packet.entities=nil;packet.entityStyles=nil
  else B.sentVisualRevision=B.visualRevision;B.lastFullVisualAt=sendAt end
  B.frameSequence=((B.frameSequence or B.frame or 0)+1)%4294967296;packet.wireSequence=B.frameSequence
  packet.hits={};local raw=json.encode(packet);B.lastPacketBytes=#raw
  if #raw<=60000 then B.lastSend,B.sendError=B.udp:send(raw);B.frameChunks=1
  else
   local total=math.ceil(#raw/48000);B.frameChunks=total
   if total<=128 then
    local session=(tonumber(B.client) or 0)%4294967296
    for i=0,total-1 do B.lastSend,B.sendError=B.udp:send('IAFR'..string.pack('<I4I4I2I2',session,B.frameSequence,i,total)..raw:sub(i*48000+1,(i+1)*48000)) end
   else B.sendError='Visual snapshot exceeds 6 MB; entities were not truncated' end
  end
 end
end
sendFrame=function(rendering)
 if B.sendingFrame then return end
 B.sendingFrame=true;local good,error=pcall(buildFrame,rendering);B.sendingFrame=false
 if not good then B.networkError=tostring(error);Isaac.DebugString('BRIDGE FRAME: '..B.networkError) end
end
B.tick=function() if not B.stopped then poll();syncPause();sendFrame() end end
cb(ModCallbacks.MC_POST_RENDER,function()
 local started=socket.gettime();B.frame=B.frame+1;poll();local polled=socket.gettime();syncPause();syncPausedProxies();sendFrame(true);local sent=socket.gettime();flushTextures()
 B.renderTiming={pollMs=(polled-started)*1000,sendMs=(sent-polled)*1000,textureMs=(socket.gettime()-sent)*1000}
 if game:GetNumPlayers()>0 then
  B.weaponSprites=B.weaponSprites or {}
  if B.state then for _,e in ipairs(Isaac.FindByType(EntityType.ENTITY_PROJECTILE)) do local key=e:GetData().arkNativeShot;local meta=key and B.state.skinMeta and B.state.skinMeta['weapon_'..key]
   local position=Isaac.WorldToScreen(e.Position)+e.SpriteOffset+Vector(0,e:ToProjectile().Height)
   if meta then local s=B.weaponSprites[meta.file];if not s then s=Sprite();skin(s,'weapon_'..key);B.weaponSprites[meta.file]=s end;local scale=renderTile()/(meta.pixelsPerUnit or meta.width*.78);s.Scale=Vector(scale,scale);s:Render(position)
   elseif key then mapSprite.Color=Color(1,.6,.15,1);mapSprite.Scale=Vector(2,2);mapSprite:Render(position-Vector(2,2)) end
  end end
  if B.outcome then Isaac.RenderText(B.outcome,240,60,1,.85,.3,1) end
  if active() then
   for _,group in ipairs({B.state.enemies or {},B.state.characters or {}}) do for _,e in ipairs(group) do
    local p=Isaac.WorldToScreen(point(e.x,e.y))-Vector(12,30);mapSprite.Color=Color(.08,.08,.08,1);mapSprite.Scale=Vector(12,1.5);mapSprite:Render(p)
    mapSprite.Color=Color(group==B.state.characters and .15 or .85,group==B.state.characters and .85 or .2,.2,1);mapSprite.Scale=Vector(12*math.max(0,math.min(1,e.hp/math.max(1,e.maxHp))),1.5);mapSprite:Render(p)
   end end
  end
 end
end)
Isaac.DebugString('ISAAC_ARKNIGHTS_BRIDGE_LOADED socket='..tostring(ok)..' RGON='..tostring(REPENTOGON~=nil))
