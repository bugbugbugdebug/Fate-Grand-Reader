# Converted effects: ScriptManager / ScriptCharaData / UIScriptChara integration.
# Renderer and definitions come from the converter workspace; see docs/converted-effects.md.
default vn_effects = []
default vn_fx_serial = 0

init 10 python:
    import copy
    VN_FX_ANCHORS = ("charabackeffect", "charaeffect", "backeffect", "fowardeffect", "effect")
    VN_FX_IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    VN_FX_POSE_FIELDS = ("pos", "pos_anim", "scale", "scale_anim", "rel", "rel_move", "roll_q",
                         "roll_c", "roll_anim", "roll_loop", "roll_wait", "roll_stop_q", "kind", "shake")

    def vn_fx_pose(data):
        return copy.deepcopy({k: data.get(k) for k in VN_FX_POSE_FIELDS if k in data})

    def vn_fx_checkpoint():
        # Record command-time rig changes, so new camera renders cannot move already-born
        # world particles to a later charaPut/charaMove/charaScale pose.
        now = vn_now()
        for rec in store.vn_effects:
            if rec["slot"] is None or not vn_fx_alive(rec, now):
                continue
            pose = vn_fx_pose(rec["owner"])
            history = rec["poses"]
            if pose != history[-1][1]:
                history.append((now, pose))
            cutoff = now - rec["display"].max_life - 1.0
            while len(history) > 1 and history[1][0] < cutoff:
                history.pop(0)

    def vn_fx_command_kind(name):
        name = name.lower().replace("forwardeffect", "fowardeffect")
        for anchor in VN_FX_ANCHORS:
            if name.startswith(anchor):
                op = name[len(anchor):]
                if op in ("", "pause", "start", "stop", "destroy", "forcestop"):
                    return anchor, op
        return None

    def vn_fx_name(name):
        name = vn_convert_name(name)
        return name[5:] if name.lower().startswith("talk/") else name

    def vn_fx_elapsed(rec, now=None):
        return 0.0 if rec["paused"] else max(0.0, (vn_now() if now is None else now) - rec["start"])

    def vn_fx_alive(rec, now=None):
        if rec["slot"] is not None:
            # A replacement charaSet/imageSet destroys the old rig and its children.
            if store.current_chara_defs.get(rec["slot"]) is not rec["owner"]:
                return False
        if rec["paused"]:
            return True
        end = _fgo_fx_done_time(rec.get("spec") or fgo_fx_defs[rec["name"]], rec["stop"])
        return end is None or vn_fx_elapsed(rec, now) < end

    def vn_fx_prune():
        store.vn_effects = [r for r in store.vn_effects if vn_fx_alive(r)]

    def vn_fx_reset():
        store.vn_effects = []
        store.vn_fx_serial = 0

    def vn_fx_geometry(rec, now=None, historical=False):
        """EffectBase in NGUI world units; independent of sprite alpha/face/offset metadata."""
        now = vn_now() if now is None else now
        x, y = rec["offset"]
        if rec.get("special"):
            sx, sy = vn_special_child_offset(rec, now)
            x, y = x + sx, y + sy
        scale = 1.0
        R = VN_FX_IDENTITY
        if rec["slot"] is not None:
            data = rec["owner"]
            if historical:
                data = rec["poses"][0][1]
                for time, pose in rec["poses"]:
                    if time > now:
                        break
                    data = pose
            pos = vn_anim_value(data["pos_anim"], now)[0] if data.get("pos_anim") else data.get("pos", (0, 0))
            scale = vn_anim_value(data["scale_anim"], now)[0] if data.get("scale_anim") else data.get("scale", 1.0)
            rel, _ = vn_rel_value(data, now)
            q, _ = vn_roll_value(data, now)
            R = vn_quat_matrix(q)
            c = data.get("roll_c") or (0.0, 0.0)
            # EndSet overwrites prefab EffectBase.xy with GetCenterOffset (0,-288).
            # Image Depth additionally cancels CharaBase's +288 before Scale.
            image = data.get("kind") in ("image", "script_image")
            by = -288.0
            p = _fgo_fx_mv(R, (x + c[0], y + by + c[1], 0.0))
            x = pos[0] + rel[0] + scale * (p[0] - c[0])
            y = pos[1] + rel[1] + (0.0 if image else 288.0) + scale * (p[1] - c[1])
            sh = data.get("shake")
            if sh and now < sh["end"]:
                tick = int(max(0.0, now - sh["start"]) / sh["cycle"])
                rng = random.Random(str(sh["start"]) + ":" + str(tick))
                x += rng.uniform(-sh["x"], sh["x"])
                y += rng.uniform(-sh["y"], sh["y"])
        flip = rec["flip"]
        F = ((-1.0 if flip in ("H", "F") else 1.0, 0.0, 0.0),
             (0.0, -1.0 if flip in ("V", "F") else 1.0, 0.0),
             (0.0, 0.0, -1.0 if flip in ("H", "V") else 1.0))
        return x, y, float(scale), _fgo_fx_m3mul(R, F)

    def vn_fx_depth(rec):
        if rec["slot"] is not None:
            dz = -2.0 if rec["anchor"] == "charabackeffect" else (1.0 if rec["anchor"] == "specialeffect" else 2.0)
            return 20.0 + 10.0 * vn_effective_depth(rec["owner"]) + dz
        return 12.0 if rec["anchor"] == "backeffect" else 100.0

    def vn_fx_stage_items(group=None):
        """One depth-sorted list of figures and effect rigs, including invisible dummy slots."""
        result = []
        for slot, data in store.current_chara_defs.items():
            if data.get("sub_group") == group and vn_slot_is_drawn(data):
                result.append((20.0 + 10.0 * vn_effective_depth(data), 0, slot, "slot", slot))
        for rec in store.vn_effects:
            if rec["anchor"] == "fowardeffect" or rec["paused"] or not vn_fx_alive(rec):
                continue
            g = rec["owner"].get("sub_group") if rec["slot"] is not None else None
            if g == group:
                result.append((vn_fx_depth(rec), 1, rec["serial"], "fx", rec))
        result.extend(vn_special_stage_items(group))
        result.sort(key=lambda item: item[:3])
        return [(item[3], item[4]) for item in result]

    def vn_fx_forward():
        return [r for r in store.vn_effects if r["anchor"] == "fowardeffect" and not r["paused"] and vn_fx_alive(r)]

    def vn_fx_select(anchor, args):
        slot = args[0] if anchor.startswith("chara") and args else None
        name_args = args[1:] if anchor.startswith("chara") else args
        name = vn_fx_name(name_args[0]) if name_args else None
        return [r for r in store.vn_effects if r["anchor"] == anchor and
                (slot is None or r["slot"] == slot) and (name is None or r["name"] == name)]

    _vn_fx_art_cache = {}

    def vn_fx_art_present(name, spec):
        """False when a texture the converted effect draws is not in the game folder (effect is skipped)."""
        ok = _vn_fx_art_cache.get(name)
        if ok is None:
            ok = True
            stack = [spec]
            while stack and ok:
                v = stack.pop()
                if isinstance(v, str):
                    if v.startswith("gen/") and not (renpy.loadable("assets/fx/%s.png" % v) or renpy.loadable("assets/fx/%s.rgba.z" % v)):
                        ok = False
                elif isinstance(v, dict):
                    stack.extend(v.values())
                elif isinstance(v, (list, tuple)):
                    stack.extend(v)
            if not ok:
                renpy.log("vn_fx: textures missing for %s; effect skipped" % name)
            _vn_fx_art_cache[name] = ok
        return ok

    def vn_fx_command(name, args, now=None):
        kind = vn_fx_command_kind(name)
        if kind is None:
            return False
        anchor, op = kind
        vn_fx_prune()
        now = vn_now() if now is None else now
        if op in ("", "pause"):
            chara = anchor.startswith("chara")
            if len(args) < (2 if chara else 1):
                return True
            slot = args[0] if chara else None
            owner = store.current_chara_defs.get(slot) if chara else None
            if chara and owner is None:
                return True
            a = args[1:] if chara else args
            effect = vn_fx_name(a[0])
            if effect not in fgo_fx_defs or not vn_fx_art_present(effect, fgo_fx_defs[effect]):
                store.vn_unrendered_wait = True
                return True
            spec = _fgo_fx_delay_spec(effect, fgo_fx_defs[effect])
            if (chara and spec.get("cams")) or (anchor == "fowardeffect" and any(e.get("zwrite") for e in spec.get("emitters", ()))):
                renpy.log("vn_fx: unsupported anchor %s for %s (donor rendering restriction)" % (anchor, effect))
                store.vn_unrendered_wait = True
                return True
            if vn_skipping() and not spec["loop"] and op != "pause":
                return True
            # GetCharaOffset(index) is ZERO for all three entries, unlike GetPosition.
            offset = (0.0, 0.0)
            if len(a) > 1:
                offset = vn_parse_position(a[1]) if not chara or "," in a[1] else offset
            flip = a[2] if len(a) > 2 and a[2] in ("H", "V", "F") else ""
            store.vn_fx_serial += 1
            rec = dict(name=effect, anchor=anchor, slot=slot, owner=owner, offset=offset,
                       flip=flip, paused=op == "pause", start=now, stop=None, serial=store.vn_fx_serial)
            rec["spec"] = spec
            rec["poses"] = [(now, vn_fx_pose(owner))] if owner is not None else []
            if vn_skipping() and spec["loop"] and op != "pause":
                rec["start"] -= spec["clips"].get("start") or 0.0
            rec["display"] = VNConvertedEffect(rec)
            store.vn_effects.append(rec)
            store.vn_unrendered_wait = False
            return True
        chosen = vn_fx_select(anchor, args)
        for rec in chosen:
            if op == "start":
                if rec["paused"]:
                    spec = fgo_fx_defs[rec["name"]]
                    if vn_skipping() and not spec["loop"]:
                        store.vn_effects.remove(rec)
                        continue
                    rec["paused"] = False
                    rec["start"] = now
                    if vn_skipping() and spec["loop"]:
                        rec["start"] -= spec["clips"].get("start") or 0.0
            elif op == "destroy" or vn_skipping():
                store.vn_effects.remove(rec)
            elif op in ("stop", "forcestop"):
                if rec["paused"]:
                    store.vn_effects.remove(rec)
                elif rec["stop"] is None:
                    rec["stop"] = vn_fx_elapsed(rec, now)
                if op == "forcestop" and rec in store.vn_effects:
                    # CommonEffectComponent.ForceStop halts the current animation; the next
                    # update enters _end immediately instead of finishing the current loop.
                    original = rec.get("spec") or fgo_fx_defs[rec["name"]]
                    if original["has_anim"]:
                        spec = dict(original)
                        spec["clips"] = dict(original["clips"])
                        force_at = vn_fx_elapsed(rec, now)
                        spec["vn_force_t7"] = force_at
                        if (spec["clips"].get("start") or 0.0) > force_at:
                            spec["clips"]["start"] = force_at
                        rec["spec"] = spec
        return True

    def vn_fx_wait(tag, args):
        kind = vn_fx_command_kind(tag)
        if kind is None:
            return False
        anchor, op = kind
        if vn_skipping() or op == "start":
            # CommonEffectManager.IsStart tests asset/component initialization, NOT the
            # end of the _start clip. Bundled definitions initialize synchronously, even
            # when created by effectPause. ScriptManager waits while IsStart is FALSE.
            return True
        # IsBusy waits through destruction, with an optional name and/or character slot.
        while True:
            now = vn_now()
            pending = []
            for rec in vn_fx_select(anchor, args):
                if not vn_fx_alive(rec, now):
                    continue
                pending.append(rec)
            if not pending or vn_skipping():
                break
            renpy.pause(0.03, hard=True)
        vn_fx_prune()
        return True

    class VNConvertedEffect(FGOFXCloud):
        def __init__(self, rec):
            super(VNConvertedEffect, self).__init__(rec["name"], layer13=rec["anchor"] != "fowardeffect",
                anchor="forwardeffect" if rec["anchor"] == "fowardeffect" else rec["anchor"])
            self.record = rec
            self.native_width = 1024.0
            self.root_matrix = VN_FX_IDENTITY
            self.birth_roots = {}

        def render(self, width, height, st, at):
            rec = self.record
            if rec["paused"] or not vn_fx_alive(rec) or not vn_special_child_visible(rec):
                return renpy.Render(width, height)
            x, y, scale, R = vn_fx_geometry(rec)
            self.x, self.y, self.scale = x, -y, scale
            self.root_matrix = R
            self.spec = rec.get("spec") or fgo_fx_defs[rec["name"]]
            self.stop_at = rec["stop"]
            # Stage/sub-camera canvases are in native NGUI units, including the wider square RT.
            self.native_width = float(width)
            self.frame_width = 1024.0
            elapsed = vn_fx_elapsed(rec)
            cutoff = elapsed - self.max_life - 1.0
            self.birth_roots = {k: v for k, v in self.birth_roots.items() if k[1] >= cutoff}
            return super(VNConvertedEffect, self).render(width, height, elapsed, at)

        def parent_particle(self, ei, e, birth, now):
            # World-space particles retain the root pose at birth. Cache on the displayable,
            # never in the store or on shared converter definitions.
            if e.get("sim_space") == "world":
                key = (ei, birth)
                if key not in self.birth_roots:
                    self.birth_roots[key] = vn_fx_geometry(self.record, self.record["start"] + birth, historical=True)
                return self.birth_roots[key]
            return self.x, -self.y, self.scale, self.root_matrix

init 20 python:
    def vn_fx_track_command(fn):
        def execute(*args, **kwargs):
            try:
                vn_special_tick()
                return fn(*args, **kwargs)
            finally:
                # Finished effects already draw nothing and stop redrawing; dropping their
                # records here also frees their caches instead of keeping them until the
                # next effect command.
                vn_fx_prune()
                vn_fx_checkpoint()
        return execute

    vn_execute_command = vn_fx_track_command(vn_execute_command)
    apply_reader_node = vn_fx_track_command(apply_reader_node)

screen vn_forward_effects():
    # MargePanel: PictureFrame(-10), forward EffectBase(-100), FlashMesh(-200).
    zorder 46
    fixed at vn_camera_transform(include_shake=False):
        xysize (config.screen_width, config.screen_height)
        fixed at Transform(zoom=upscale_ratio):
            xysize (original_screen_width, original_screen_height)
            yalign 1.0
            for fx in vn_fx_forward():
                add fx["display"]
