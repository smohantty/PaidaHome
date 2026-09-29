"""Build the 20x40 modern duplex in Blender and render photoreal views with Cycles.

Usage:
  blender -b -P blender/render_house.py -- --out renders --samples 128 --res 1600x1000 --views all
  blender -b -P blender/render_house.py -- --blend blender/duplex.blend --views none   # just save the scene

Geometry mirrors index.html: plan units are feet, x = west->east (0..20), y = south(road)->north (0..40).
"""
import argparse
import math
import os
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument('--out', default='renders')
ap.add_argument('--samples', type=int, default=128)
ap.add_argument('--res', default='1600x1000')
ap.add_argument('--views', default='all')
ap.add_argument('--blend', default='')
args = ap.parse_args(argv)

FT = 0.3048
FLOOR, RES, T = 10, 0.1, 0.5


def P(x, y, h):
    return Vector(((x - 10) * FT, (y - 20) * FT, h * FT))


# ---------------------------------------------------------------- house data
LEVELS = [
    dict(name='Ground floor', wallH=9.5,
         rooms=[('Front setback', (0, 0, 20, 3), 'paving'), ('Front garden', (0, 3, 9, 3), 'paving'),
                ('Porch', (9, 3, 5, 3), 'stone'), ('Planter', (14, 3, 6, 3), 'paving'),
                ('Bedroom 1', (0, 6, 10, 9), 'wood'), ('Bath 1', (0, 15, 6, 4), 'bath'), ('Dress 1', (6, 15, 4, 4), 'wood'),
                ('Foyer', (10, 6, 3.5, 11), 'stone'), ('Kitchen', (13.5, 6, 6.5, 11), 'tile'),
                ('Stair', (0, 19, 10, 7), 'stone'), ('Dining', (10, 17, 10, 9), 'wood'),
                ('Store', (0, 26, 5, 7), 'tile'), ('Powder', (0, 33, 5, 5), 'bath'),
                ('Living', (5, 26, 15, 12), 'wood'), ('Pooja', (16, 34, 4, 4), 'stone'),
                ('Rear setback', (0, 38, 20, 2), 'paving')],
         encl=((0,6,10,9),(0,15,6,4),(6,15,4,4),(10,6,3.5,11),(13.5,6,6.5,11),(0,19,10,7),(10,17,10,9),(0,26,5,7),(0,33,5,5),(5,26,15,12),(16,34,4,4)), extraWalls=[],
         open=((10,17,13.5,17),(10,19,10,22.5),(11,26,19,26),(14.5,17,17,17),(6.5,15,9.5,15),(16,34.5,16,37.5)), doors=((10.3,6,13.3,6),(10,11.5,10,14.5),(1,15,3.5,15),(5,27,5,29.5),(5,34,5,36.5)), glassdoors=[],
         windows=((6,6,9.5,6,3,7),(16.5,6,19.5,6,3.5,7),(1.5,38,3.5,38,5.5,7),(5.5,38,16,38,0,9.5)), clad=[], rails=[],
         parapets=((0,0,8,0,4),(16,0,20,0,4),(0,0,0,6,4),(20,0,20,6,4),(0,40,20,40,5),(0,38,0,40,5),(20,38,20,40,5))),
    dict(name='First floor', wallH=9.5,
         rooms=[('Bedroom 2', (0, 6, 10, 9), 'wood'), ('Bath 2', (0, 15, 6, 4), 'bath'), ('Dress 2', (6, 15, 4, 4), 'wood'),
                ('Lounge', (10, 6, 10, 11), 'wood'), ('Gallery', (10, 17, 10, 9), 'wood'), ('Walkway', (10, 26, 3, 3), 'wood'),
                ('Study', (0, 26, 10, 12), 'wood')],
         encl=((0,6,10,9),(0,15,6,4),(6,15,4,4),(10,6,10,11),(0,19,10,7),(0,26,10,12)), extraWalls=((20,17,20,38),(10,38,20,38)),
         open=((10,22.5,10,26),(10.5,17,19.5,17),(6.5,15,9.5,15)), doors=((10,11.5,10,14.5),(1,15,3.5,15),(10,26.3,10,28.8)), glassdoors=[],
         windows=((6,6,9.5,6,3,7),(12,6,18,6,2,7),(2,38,8,38,3,7),(10,38,20,38,0,9.5)), clad=((10,6,12,6),(18,6,20,6)), rails=((13,26,20,26),(13,26,13,29),(10,29,13,29)),
         parapets=[]),
    dict(name='Terrace', wallH=8,
         rooms=[('Roof terrace', (0, 3, 20, 16), 'terrace'), ('Pergola deck', (10, 19, 10, 7), 'deck'),
                ('Open terrace', (0, 26, 20, 12), 'terrace')],
         encl=[(0, 19, 10, 7)], extraWalls=[],
         open=[], doors=[(10, 20.2, 10, 23.2)], glassdoors=[], windows=[], clad=[], rails=[],
         parapets=((0,6,0,38,3.5),(20,6,20,38,3.5),(0,38,20,38,3.5))),
]

# ---------------------------------------------------------------- scene reset
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
coll = scene.collection


# ---------------------------------------------------------------- materials
def setin(node, names, val):
    for n in names:
        if n in node.inputs:
            node.inputs[n].default_value = val
            return True
    return False


def new_mat(name, color, rough=0.8, metal=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    setin(b, ['Base Color'], (*color, 1))
    setin(b, ['Roughness'], rough)
    setin(b, ['Metallic'], metal)
    return m


def textured(name, c1, c2, kind='noise', scale=(1, 1, 1), tex_scale=4.0, rough=0.7, bump=0.15, mortar=None, brick=(0.4, 0.4)):
    m = new_mat(name, c1, rough)
    nt = m.node_tree
    N, L = nt.nodes, nt.links
    b = N['Principled BSDF']
    tc = N.new('ShaderNodeTexCoord')
    mp = N.new('ShaderNodeMapping')
    mp.inputs['Scale'].default_value = scale
    L.new(tc.outputs['Object'], mp.inputs['Vector'])
    if kind == 'brick':
        t = N.new('ShaderNodeTexBrick')
        t.inputs['Color1'].default_value = (*c1, 1)
        t.inputs['Color2'].default_value = (*c2, 1)
        t.inputs['Mortar'].default_value = (*(mortar or [c * 0.7 for c in c1]), 1)
        t.inputs['Scale'].default_value = tex_scale
        t.inputs['Mortar Size'].default_value = 0.006
        t.inputs['Brick Width'].default_value = brick[0]
        t.inputs['Row Height'].default_value = brick[1]
        t.offset = 0.5 if brick[0] != brick[1] else 0.0
        L.new(mp.outputs['Vector'], t.inputs['Vector'])
        L.new(t.outputs['Color'], b.inputs['Base Color'])
        fac = t.outputs['Fac']
    else:
        t = N.new('ShaderNodeTexWave' if kind == 'wave' else 'ShaderNodeTexNoise')
        t.inputs['Scale'].default_value = tex_scale
        if kind == 'wave':
            t.inputs['Distortion'].default_value = 6
            t.inputs['Detail'].default_value = 3
        else:
            t.inputs['Detail'].default_value = 8
        L.new(mp.outputs['Vector'], t.inputs['Vector'])
        cr = N.new('ShaderNodeValToRGB')
        cr.color_ramp.elements[0].color = (*c1, 1)
        cr.color_ramp.elements[1].color = (*c2, 1)
        L.new(t.outputs['Fac'], cr.inputs['Fac'])
        L.new(cr.outputs['Color'], b.inputs['Base Color'])
        fac = t.outputs['Fac']
    if bump:
        bp = N.new('ShaderNodeBump')
        bp.inputs['Strength'].default_value = bump
        bp.inputs['Distance'].default_value = 0.002
        L.new(fac, bp.inputs['Height'])
        L.new(bp.outputs['Normal'], b.inputs['Normal'])
    return m


def glass_mat():
    m = new_mat('Glass', (0.86, 0.93, 0.95), 0.0)
    nt = m.node_tree
    N, L = nt.nodes, nt.links
    b = N['Principled BSDF']
    setin(b, ['Transmission Weight', 'Transmission'], 1.0)
    setin(b, ['IOR'], 1.45)
    out = N['Material Output']
    lp = N.new('ShaderNodeLightPath')
    tr = N.new('ShaderNodeBsdfTransparent')
    mix = N.new('ShaderNodeMixShader')
    L.new(lp.outputs['Is Shadow Ray'], mix.inputs['Fac'])
    L.new(b.outputs[0], mix.inputs[1])
    L.new(tr.outputs[0], mix.inputs[2])
    L.new(mix.outputs[0], out.inputs['Surface'])
    return m


def emit_mat(name, color, strength):
    m = new_mat(name, color, 0.5)
    b = m.node_tree.nodes['Principled BSDF']
    setin(b, ['Emission Color', 'Emission'], (*color, 1))
    setin(b, ['Emission Strength'], strength)
    return m


M = dict(
    wall=textured('Plaster', (0.90, 0.89, 0.86), (0.84, 0.83, 0.80), 'noise', tex_scale=30, rough=0.9, bump=0.05),
    frame=textured('Charcoal concrete', (0.025, 0.027, 0.03), (0.045, 0.047, 0.05), 'noise', tex_scale=12, rough=0.75, bump=0.08),
    clad=textured('Teak cladding', (0.30, 0.15, 0.07), (0.45, 0.25, 0.12), 'wave', scale=(1, 1, 0.15), tex_scale=6, rough=0.55, bump=0.1),
    glass=glass_mat(),
    wood=textured('Oak floor', (0.55, 0.36, 0.2), (0.68, 0.48, 0.3), 'wave', scale=(0.2, 1, 1), tex_scale=5, rough=0.35, bump=0.05),
    tile=textured('Porcelain tile', (0.84, 0.82, 0.78), (0.8, 0.78, 0.74), 'brick', tex_scale=2.2, brick=(0.5, 0.5), rough=0.25, bump=0.3),
    bath=textured('Bath tile', (0.55, 0.62, 0.64), (0.5, 0.57, 0.6), 'brick', tex_scale=4, brick=(0.5, 0.5), rough=0.2, bump=0.3),
    stone=textured('Kota stone', (0.62, 0.6, 0.55), (0.55, 0.53, 0.49), 'noise', tex_scale=6, rough=0.4, bump=0.05),
    paving=textured('Pavers', (0.52, 0.5, 0.46), (0.46, 0.44, 0.41), 'brick', tex_scale=3, brick=(0.4, 0.2), rough=0.8, bump=0.4),
    terrace=textured('Terrace tile', (0.62, 0.52, 0.45), (0.58, 0.48, 0.41), 'brick', tex_scale=2.5, brick=(0.5, 0.5), rough=0.7, bump=0.3),
    deck=textured('WPC deck', (0.3, 0.2, 0.13), (0.38, 0.26, 0.16), 'brick', scale=(1, 0.2, 1), tex_scale=2, brick=(0.9, 0.12), rough=0.6, bump=0.3),
    slab=new_mat('Slab', (0.8, 0.79, 0.76), 0.9),
    grass=textured('Grass', (0.12, 0.22, 0.06), (0.2, 0.32, 0.1), 'noise', tex_scale=40, rough=0.95, bump=0.4),
    road=textured('Asphalt', (0.06, 0.06, 0.065), (0.1, 0.1, 0.105), 'noise', tex_scale=60, rough=0.9, bump=0.3),
    sidewalk=new_mat('Sidewalk', (0.55, 0.54, 0.52), 0.85),
    fabric=textured('Fabric', (0.25, 0.3, 0.33), (0.28, 0.33, 0.36), 'noise', tex_scale=80, rough=1.0, bump=0.1),
    linen=new_mat('Linen', (0.85, 0.84, 0.8), 0.95),
    woodDark=textured('Walnut', (0.12, 0.07, 0.04), (0.2, 0.12, 0.07), 'wave', tex_scale=5, rough=0.4, bump=0.03),
    white=new_mat('White lacquer', (0.9, 0.9, 0.88), 0.25),
    metal=new_mat('Metal', (0.6, 0.62, 0.64), 0.3, 1.0),
    black=new_mat('Black metal', (0.02, 0.02, 0.022), 0.45, 0.6),
    leaf=textured('Foliage', (0.05, 0.14, 0.03), (0.12, 0.25, 0.06), 'noise', tex_scale=25, rough=0.7, bump=0.6),
    solar=new_mat('Solar panel', (0.02, 0.04, 0.09), 0.12, 0.3),
    tank=new_mat('Water tank', (0.03, 0.03, 0.03), 0.5),
    nbrA=new_mat('Neighbour A', (0.86, 0.84, 0.79), 0.9),
    nbrB=new_mat('Neighbour B', (0.78, 0.8, 0.82), 0.9),
    darkglass=new_mat('Dark glass', (0.03, 0.04, 0.05), 0.1),
    lamp=emit_mat('Lamp', (1.0, 0.82, 0.55), 0.0),
)


# ---------------------------------------------------------------- mesh helpers
def _mesh(name, verts, faces, mat, bevel):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    me.materials.append(mat)
    if bevel:
        mod = ob.modifiers.new('bevel', 'BEVEL')
        mod.width = 0.006
        mod.segments = 2
        mod.limit_method = 'ANGLE'
    return ob


BOX_FACES = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]


def box(x1, y1, x2, y2, h1, h2, mat, name='box', bevel=True):
    if abs(x2 - x1) < 1e-6 or abs(y2 - y1) < 1e-6 or h2 <= h1:
        return None
    a = P(min(x1, x2), min(y1, y2), h1)
    b = P(max(x1, x2), max(y1, y2), h2)
    v = [(a.x, a.y, a.z), (b.x, a.y, a.z), (b.x, b.y, a.z), (a.x, b.y, a.z),
         (a.x, a.y, b.z), (b.x, a.y, b.z), (b.x, b.y, b.z), (a.x, b.y, b.z)]
    return _mesh(name, v, BOX_FACES, mat, bevel)


def cbox(sx, sy, sz, center, mat, rot=(0, 0, 0), name='cbox'):
    """Box of size (ft) centred on a world point, then rotated (radians)."""
    hx, hy, hz = sx * FT / 2, sy * FT / 2, sz * FT / 2
    v = [(-hx, -hy, -hz), (hx, -hy, -hz), (hx, hy, -hz), (-hx, hy, -hz),
         (-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz)]
    ob = _mesh(name, v, BOX_FACES, mat, True)
    ob.location = center
    ob.rotation_euler = rot
    return ob


def slab(poly, h0, th, mat, name='slab'):
    area = sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))
    if area < 0:
        poly = poly[::-1]
    n = len(poly)
    v = [tuple(P(x, y, h0)) for x, y in poly] + [tuple(P(x, y, h0 + th)) for x, y in poly]
    faces = [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]
    faces += [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    return _mesh(name, v, faces, mat, False)


def cylinder(r, depth, center, mat, verts=32, name='cyl'):
    bpy.ops.mesh.primitive_cylinder_add(radius=r * FT, depth=depth * FT, location=center, vertices=verts)
    ob = bpy.context.active_object
    ob.name = name
    ob.data.materials.append(mat)
    bpy.ops.object.shade_smooth()
    return ob


def blob(r, center, mat, sz=1.0, name='blob'):
    bpy.ops.mesh.primitive_ico_sphere_add(radius=r * FT, subdivisions=3, location=center)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale.z = sz
    ob.data.materials.append(mat)
    d = ob.modifiers.new('displace', 'DISPLACE')
    tex = bpy.data.textures.new(name + '_tex', 'CLOUDS')
    tex.noise_scale = 0.35
    d.texture = tex
    d.strength = 0.25
    bpy.ops.object.shade_smooth()
    return ob


# ---------------------------------------------------------------- walls (same run-merging as the web model)
def wall_box(o, line, a, b, h1, h2, mat, ext=0.0, name='wall'):
    if b - a <= 0 or h2 <= h1:
        return
    A, B = a - ext, b + ext
    if o == 'h':
        box(A, line - T / 2, B, line + T / 2, h1, h2, mat, name)
    else:
        box(line - T / 2, A, line + T / 2, B, h1, h2, mat, name)


def glass_pane(o, line, a, b, h1, h2):
    t = 0.08
    if o == 'h':
        box(a, line - t, b, line + t, h1, h2, M['glass'], 'glass', False)
    else:
        box(line - t, a, line + t, b, h1, h2, M['glass'], 'glass', False)


def build_walls(lv, e):
    segs = {}

    def put(s, cls, force=False):
        x1, y1, x2, y2 = s[:4]
        hz = abs(y1 - y2) < 1e-6
        o = 'h' if hz else 'v'
        li = round((y1 if hz else x1) / RES)
        a = round(min(x1, x2) / RES) if hz else round(min(y1, y2) / RES)
        b = round(max(x1, x2) / RES) if hz else round(max(y1, y2) / RES)
        for i in range(a, b):
            k = (o, li, i)
            if force or k not in segs:
                segs[k] = cls

    for x, y, w, h in lv['encl']:
        put((x, y, x + w, y), 'wall'); put((x, y + h, x + w, y + h), 'wall')
        put((x, y, x, y + h), 'wall'); put((x + w, y, x + w, y + h), 'wall')
    for s in lv['extraWalls']:
        put(s, 'wall')
    for p in lv['parapets']:
        put(p, ('par', p[4]))
    for s in lv['open']:
        put(s, 'open', True)
    for s in lv['doors']:
        put(s, 'door', True)
    for s in lv['glassdoors']:
        put(s, 'gdoor', True)
    for s in lv['windows']:
        put(s, ('win', s[4], s[5]), True)
    for s in lv['clad']:
        put(s, 'clad', True)
    for s in lv['rails']:
        put(s, 'rail', True)

    H = lv['wallH']
    lines = {}
    for (o, li, i), cls in segs.items():
        lines.setdefault((o, li), []).append((i, cls))

    def emit(o, li, i0, i1, c):
        line, a, b = li * RES, i0 * RES, (i1 + 1) * RES
        if c == 'wall':
            wall_box(o, line, a, b, e, e + H, M['wall'], T / 2)
        elif isinstance(c, tuple) and c[0] == 'par':
            wall_box(o, line, a, b, e, e + c[1], M['wall'], T / 2, 'parapet')
        elif c == 'door':
            wall_box(o, line, a, b, e + 7, e + H, M['wall'])
        elif c == 'gdoor':
            wall_box(o, line, a, b, e + 7, e + H, M['wall']); glass_pane(o, line, a, b, e, e + 7)
        elif isinstance(c, tuple) and c[0] == 'win':
            sill, head = c[1], c[2]
            wall_box(o, line, a, b, e, e + sill, M['wall'])
            wall_box(o, line, a, b, e + head, e + H, M['wall'])
            glass_pane(o, line, a, b, e + sill, e + head)
            # slim black frame: mullions every ~4 ft plus head/sill
            n = max(1, math.ceil((b - a) / 4))
            for k in range(n + 1):
                m = a + (b - a) * k / n
                m = min(max(m, a + 0.08), b - 0.08)
                if o == 'h':
                    box(m - 0.08, line - 0.12, m + 0.08, line + 0.12, e + sill, e + head, M['black'], 'mullion')
                else:
                    box(line - 0.12, m - 0.08, line + 0.12, m + 0.08, e + sill, e + head, M['black'], 'mullion')
            for hh in (sill, head - 0.15):
                if o == 'h':
                    box(a, line - 0.12, b, line + 0.12, e + hh, e + hh + 0.15, M['black'], 'transom')
        elif c == 'clad':
            wall_box(o, line, a, b, e, e + H, M['clad'], T / 2, 'clad')
        elif c == 'rail':
            glass_pane(o, line, a, b, e, e + 3.5)
            wall_box(o, line, a, b, e + 3.45, e + 3.6, M['black'], 0, 'handrail')

    for (o, li), arr in lines.items():
        arr.sort()
        st, prev = arr[0], arr[0]
        for s in arr[1:]:
            if s[0] == prev[0] + 1 and s[1] == st[1]:
                prev = s
                continue
            emit(o, li, st[0], prev[0], st[1])
            st = prev = s
        emit(o, li, st[0], prev[0], st[1])


def stairs(e):
    r, t = FLOOR / 16, 6.5 / 7
    for k in range(1, 8):
        top = e + k * r
        box(10 - k * t, 19, 10 - (k - 1) * t, 22.5, max(e, top - 1), top, M['stone'], 'step')
    box(0, 19, 3.5, 26, e + 8 * r - 0.6, e + 8 * r, M['stone'], 'landing')
    for k in range(1, 8):
        top = e + 8 * r + k * r
        box(3.5 + (k - 1) * t, 22.5, 3.5 + k * t, 26, max(e, top - 1), top, M['stone'], 'step')
    box(3.5, 22.44, 10, 22.56, e + 5 + 3, e + 5 + 3.12, M['black'], 'rail')


# ---------------------------------------------------------------- assemble
box(0, 3, 20, 38, -0.5, 0, M['slab'], 'ground slab', False)
slab([(0, 6), (20, 6), (20, 26), (13, 26), (13, 29), (10, 29), (10, 38), (0, 38), (0, 26), (10, 26), (10, 19), (0, 19)], 9.5, 0.5, M['slab'], 'first slab')
slab([(0, 3), (20, 3), (20, 38), (0, 38), (0, 26), (10, 26), (10, 19), (0, 19)], 19.5, 0.5, M['slab'], 'roof slab')
box(-0.25, 18.75, 10.25, 26.25, 28, 28.5, M['frame'], 'stair room roof')

for i, lv in enumerate(LEVELS):
    e = i * FLOOR
    build_walls(lv, e)
    for name, (x, y, w, h), f in lv['rooms']:
        box(x, y, x + w, y + h, e, e + 0.04, M[f], 'floor ' + name, False)
stairs(0)
stairs(FLOOR)

# main door (closed)
a = 0.0
cbox(3, 0.18, 7, P(10.3 + 1.5 * math.cos(a), 6 + 1.5 * math.sin(a), 3.5), M['woodDark'], (0, 0, a), 'main door')

# modern facade: charcoal frame + teak fins
box(-0.45, 2.6, 0.45, 6.3, 0, 23.5, M['frame'], 'frame west')
box(19.55, 2.6, 20.45, 6.3, 0, 23.5, M['frame'], 'frame east')
box(-0.45, 2.6, 20.45, 3.4, 19.5, 23.5, M['frame'], 'frame top')
box(0, 3, 20, 6, 19.35, 19.5, M['frame'], 'frame soffit')
x = 10.4
while x < 19.6:
    box(x, 5.2, x + 0.22, 5.8, 10.5, 19.3, M['clad'], 'fin')
    x += 0.8

# gate
x = 8.2
while x < 15.9:
    box(x, -0.06, x + 0.12, 0.06, 0.2, 4.2, M['black'], 'gate bar', False)
    x += 0.45
box(8, -0.08, 16, 0.08, 0.2, 0.45, M['black'], 'gate rail')
box(8, -0.08, 16, 0.08, 3.9, 4.2, M['black'], 'gate rail')


def F(lvl, x1, y1, x2, y2, h1, h2, mat, name='furniture'):
    return box(x1, y1, x2, y2, lvl * FLOOR + h1, lvl * FLOOR + h2, M[mat], name)


# south-west bedrooms on both floors: bed head to the south, wardrobe in the dress area, bath fixtures
for L in (0, 1):
    F(L, 0.5, 6.3, 5.5, 12.8, 0, 1.8, 'linen', 'bed'); F(L, 0.5, 6.3, 5.5, 6.65, 0, 3.6, 'clad' if L else 'woodDark', 'headboard')
    F(L, 6.25, 17.1, 9.75, 18.75, 0, 7, 'woodDark', 'wardrobe')
    F(L, 4.5, 15.3, 5.75, 16.8, 0, 1.4, 'white', 'wc'); F(L, 0.25, 17.5, 1.5, 18.75, 0, 2.8, 'white', 'vanity')
F(0, 10.25, 7.5, 11, 10.5, 0, 3.5, 'woodDark', 'shoe cabinet')
# kitchen (south-east): fridge SW, hob on the east wall, sink counter NE
F(0, 13.75, 6.25, 16, 8.5, 0, 6, 'metal', 'fridge')
F(0, 18, 6.25, 19.75, 14.5, 0, 3, 'white', 'hob counter'); F(0, 18, 6.25, 19.75, 14.5, 3, 3.1, 'stone', 'counter top')
F(0, 18.3, 8.5, 19.5, 11, 3.1, 3.16, 'black', 'hob'); F(0, 18.4, 8.7, 19.75, 10.8, 6.2, 7.2, 'metal', 'chimney hood')
F(0, 16.5, 14.75, 19.75, 16.75, 0, 3, 'white', 'sink counter'); F(0, 16.5, 14.75, 19.75, 16.75, 3, 3.1, 'stone', 'counter top')
# dining
F(0, 13, 20, 17, 23, 2.35, 2.5, 'woodDark', 'dining top'); F(0, 14.7, 21.2, 15.3, 21.8, 0, 2.35, 'black', 'dining base')
for cx, cy in [(13.8, 19.3), (16.2, 19.3), (13.8, 23.7), (16.2, 23.7), (12.3, 21.5), (17.7, 21.5)]:
    F(0, cx - 0.55, cy - 0.55, cx + 0.55, cy + 0.55, 1.4, 1.55, 'woodDark', 'chair seat')
    F(0, cx - 0.05, cy - 0.05, cx + 0.05, cy + 0.05, 0, 1.4, 'black', 'chair leg')
# living (north-east, double height)
F(0, 5.3, 28, 7.8, 35, 0.3, 1.5, 'fabric', 'sofa'); F(0, 5.3, 28, 6, 35, 1.5, 2.9, 'fabric', 'sofa back')
F(0, 5.4, 28.1, 7.7, 34.9, 0, 0.3, 'black', 'sofa base')
F(0, 10, 30, 12.5, 33, 0, 1.3, 'woodDark', 'coffee table'); F(0, 8.5, 28.5, 14, 34.5, 0, 0.03, 'linen', 'rug')
F(0, 19.2, 28, 19.75, 32, 0, 1.8, 'woodDark', 'tv unit'); F(0, 19.65, 28.5, 19.75, 31.5, 3, 5.6, 'black', 'tv')
F(0, 12.45, 31.95, 12.55, 32.05, 12.2, 19.5, 'black', 'pendant rod')
cylinder(1.6, 0.25, P(12.5, 32, 12.1), M['lamp'], 48, 'pendant')
cylinder(0.5, 1.4, P(14, 36.8, 0.7), M['black'], 24, 'planter')
blob(1.3, P(14, 36.8, 3.6), M['leaf'], 1.7, 'plant')
box(16, 34, 20, 38, 9.5, 10, M['slab'], 'pooja ceiling')
F(0, 19.2, 35, 19.75, 37, 0, 4, 'woodDark', 'pooja shelf')
box(5, 39.55, 19, 39.75, 0.5, 5, M['leaf'], 'green wall')
# store + powder
F(0, 0.25, 26.5, 1.5, 32.5, 0, 7, 'woodDark', 'store shelves')
F(0, 0.3, 36, 1.8, 37.6, 0, 1.4, 'white', 'wc'); F(0, 0.25, 33.5, 1.5, 35, 0, 2.8, 'white', 'vanity')
# first floor: lounge, gallery, study
F(1, 12.5, 6.3, 17.5, 8.3, 0.3, 1.5, 'fabric', 'window seat')
F(1, 17.5, 10, 19.75, 15.5, 0.3, 1.5, 'fabric', 'sofa'); F(1, 19.1, 10, 19.75, 15.5, 1.5, 2.9, 'fabric', 'sofa back')
F(1, 13.5, 11, 15.8, 13.8, 0, 1.3, 'woodDark', 'table')
F(1, 19.2, 18, 19.75, 24, 0, 7, 'woodDark', 'bookshelf'); F(1, 15, 19.5, 16.5, 21, 0, 1.6, 'fabric', 'armchair'); F(1, 15, 22.5, 16.5, 24, 0, 1.6, 'fabric', 'armchair')
F(1, 2, 36, 8, 37.75, 2.4, 2.5, 'woodDark', 'desk'); F(1, 4.3, 34.2, 5.7, 35.5, 0, 1.5, 'fabric', 'chair')
F(1, 0.25, 27, 1.1, 33, 0, 7, 'woodDark', 'bookshelf'); F(1, 6, 27, 9.7, 30, 0, 1.5, 'fabric', 'daybed')
# terrace: pergola (centre-east), solar over the lounge, tank in the south-west
x = 10.6
while x < 20:
    F(2, x, 19.2, x + 0.3, 25.8, 8.2, 8.6, 'clad', 'pergola slat')
    x += 1.1
F(2, 10, 19.2, 20, 19.6, 7.8, 8.2, 'frame', 'pergola beam'); F(2, 10, 25.4, 20, 25.8, 7.8, 8.2, 'frame', 'pergola beam')
F(2, 19.4, 19.2, 19.8, 19.6, 0, 7.8, 'frame', 'pergola post'); F(2, 19.4, 25.4, 19.8, 25.8, 0, 7.8, 'frame', 'pergola post')
F(2, 12, 21, 16, 23.5, 0.3, 1.4, 'fabric', 'lounger')
F(2, 1, 13, 5, 17, 0, 1.6, 'woodDark', 'planter box')
blob(1.6, P(3, 15, 2 * FLOOR + 2.6), M['leaf'], 0.8, 'terrace plants')
for cy in (8.3, 11.8, 15.3):
    cbox(8.4, 3.3, 0.15, P(15, cy, 2 * FLOOR + 1.3), M['solar'], (math.radians(13), 0, 0), 'solar panel')
cylinder(1.7, 4, P(3.5, 9.5, 2 * FLOOR + 1.5 + 2), M['tank'], 40, 'water tank')  # south-west corner of the roof
box(1, 7, 6, 12, 2 * FLOOR, 2 * FLOOR + 1.5, M['frame'], 'tank plinth')
box(0.6, 38.3, 4, 39.7, 0, 0.06, M['frame'], 'septic cover (NW)')
box(16, 38.3, 19.4, 39.7, 0, 0.06, M['frame'], 'sump cover (NE)')

# site
bpy.ops.mesh.primitive_plane_add(size=160, location=(0, 0, -0.55 * FT))
bpy.context.active_object.data.materials.append(M['grass'])
box(0, 0, 20, 40, -0.55, -0.05, M['paving'], 'plot paving', False)
box(-60, -14, 80, -1.5, -0.55, -0.45, M['road'], 'road', False)
box(-60, -1.5, 80, 0, -0.55, -0.2, M['sidewalk'], 'sidewalk', False)
box(-21, 3, -0.02, 38, 0, 20, M['nbrA'], 'neighbour west')
box(20.02, 3, 41, 38, 0, 29, M['nbrB'], 'neighbour east')
for (x1, x2, h1, h2) in [(-16, -5, 3, 8), (-16, -5, 13, 18)]:
    box(x1, 2.9, x2, 3.05, h1, h2, M['darkglass'], 'nbr window')
for (x1, x2, h1, h2) in [(25, 36, 3, 8), (25, 36, 13, 18), (25, 36, 23, 27)]:
    box(x1, 2.9, x2, 3.05, h1, h2, M['darkglass'], 'nbr window')
for tx in (-11, 33):
    cylinder(0.3, 8, P(tx, -3, 4), M['woodDark'], 12, 'tree trunk')
    for dx, dy, dh, rr in ((0, 0, 11, 3.2), (1.8, 0.8, 12.5, 2.4), (-1.6, -0.5, 12.2, 2.5), (0.3, -1, 13.8, 2.0)):
        blob(rr, P(tx + dx, -3 + dy, dh), M['leaf'], 0.85, 'tree canopy')

# ---------------------------------------------------------------- lighting
world = bpy.data.worlds.new('World')
scene.world = world
world.use_nodes = True
wn = world.node_tree.nodes
sky = wn.new('ShaderNodeTexSky')
for st in ('MULTIPLE_SCATTERING', 'NISHITA', 'HOSEK_WILKIE'):
    try:
        sky.sky_type = st
        break
    except TypeError:
        continue
if hasattr(sky, 'sun_disc'):
    sky.sun_disc = False
bg = wn['Background']
world.node_tree.links.new(sky.outputs['Color'], bg.inputs['Color'])

sun_data = bpy.data.lights.new('Sun', 'SUN')
sun_data.angle = math.radians(1.2)
sun = bpy.data.objects.new('Sun', sun_data)
coll.objects.link(sun)

WARM = (1.0, 0.72, 0.45)
night_lights = []


def area(name, x, y, h, size, power, shape='SQUARE'):
    d = bpy.data.lights.new(name, 'AREA')
    d.size = size * FT
    d.energy = power
    d.color = WARM
    ob = bpy.data.objects.new(name, d)
    ob.location = P(x, y, h)
    ob.visible_camera = False
    coll.objects.link(ob)
    night_lights.append(ob)


def spot(name, x, y, h, power, rot, size=35):
    d = bpy.data.lights.new(name, 'SPOT')
    d.energy = power
    d.color = WARM
    d.spot_size = math.radians(size)
    d.spot_blend = 0.6
    ob = bpy.data.objects.new(name, d)
    ob.location = P(x, y, h)
    ob.rotation_euler = rot
    coll.objects.link(ob)
    night_lights.append(ob)


area('living light', 12.5, 32, 19.2, 4, 500)
area('dining light', 15, 21.5, 9.2, 2, 180)
area('kitchen light', 16.75, 11.5, 9.2, 3, 180)
area('foyer light', 11.75, 11, 9.2, 1.5, 60)
area('bed1 light', 5, 10.5, 9.2, 3, 120)
area('lounge light', 15, 11.5, 19.2, 3, 150)
area('gallery light', 15, 21.5, 19.2, 3, 150)
area('bed2 light', 5, 10.5, 19.2, 3, 120)
area('study light', 5, 32, 19.2, 3, 120)
spot('porch downlight', 11.8, 4.5, 19.2, 250, (0, 0, 0), 60)
spot('frame uplight west', 0.2, 4.2, 0.3, 120, (math.radians(180), 0, 0), 25)
spot('frame uplight east', 19.8, 4.2, 0.3, 120, (math.radians(180), 0, 0), 25)
spot('fin washer', 15, 1.2, 0.3, 200, (math.radians(160), 0, 0), 40)
area('pergola light', 15, 22.5, 27.8, 3, 80)

LAT = math.radians(13)


def sun_dir(hour, decl):
    d, H = math.radians(decl), math.radians((hour - 12) * 15)
    E = -math.cos(d) * math.sin(H)
    N = math.sin(d) * math.cos(LAT) - math.cos(d) * math.cos(H) * math.sin(LAT)
    U = math.sin(d) * math.sin(LAT) + math.cos(d) * math.cos(H) * math.cos(LAT)
    return Vector((E, N, U)).normalized()


def set_lighting(hour, decl, night=False):
    v = sun_dir(hour, decl)
    sun.rotation_euler = (-v).to_track_quat('-Z', 'Y').to_euler()
    elev = math.asin(max(-1, min(1, v.z)))
    if hasattr(sky, 'sun_elevation'):
        sky.sun_elevation = max(elev, math.radians(0.5))
        sky.sun_rotation = math.atan2(v.x, v.y)
    if night:
        sun_data.energy = 1.2
        sun_data.color = (1.0, 0.55, 0.3)
        bg.inputs['Strength'].default_value = 0.25
        M['lamp'].node_tree.nodes['Principled BSDF'].inputs['Emission Strength'].default_value = 25
    else:
        sun_data.energy = 4.5
        sun_data.color = (1.0, 0.96, 0.9)
        bg.inputs['Strength'].default_value = 0.35
        M['lamp'].node_tree.nodes['Principled BSDF'].inputs['Emission Strength'].default_value = 2
    for ob in night_lights:
        ob.hide_render = not night


# ---------------------------------------------------------------- camera + render settings
cam_data = bpy.data.cameras.new('Camera')
cam = bpy.data.objects.new('Camera', cam_data)
coll.objects.link(cam)
scene.camera = cam

VIEWS = {
    'front':   dict(cam=(28, -24, 5.5), tgt=(8.5, 12, 11), lens=26, hour=11, decl=-23.44, exposure=0.0),
    'aerial':  dict(cam=(-26, -30, 52), tgt=(10, 20, 8), lens=35, hour=15, decl=0, exposure=0.0),
    'living':  dict(cam=(12.5, 27.2, 5.0), tgt=(11, 37.5, 10.5), lens=16, hour=10, decl=-23.44, exposure=1.2),
    'gallery': dict(cam=(15.5, 22.6, 16.2), tgt=(12.5, 37, 3), lens=18, hour=10, decl=-23.44, exposure=1.0),
    'dusk':    dict(cam=(23, -21, 5), tgt=(9, 12, 11), lens=28, hour=17.95, decl=0, exposure=0.8, night=True),
}

scene.render.engine = 'CYCLES'
try:
    prefs = bpy.context.preferences.addons['cycles'].preferences
    for dev_type in ('METAL', 'OPTIX', 'CUDA', 'HIP', 'ONEAPI'):
        try:
            prefs.compute_device_type = dev_type
            prefs.get_devices()
            if any(d.type == dev_type for d in prefs.devices):
                for d in prefs.devices:
                    d.use = True
                scene.cycles.device = 'GPU'
                print('Cycles device:', dev_type)
                break
        except TypeError:
            continue
except Exception as ex:  # CPU fallback
    print('GPU setup failed, using CPU:', ex)

scene.cycles.samples = args.samples
scene.cycles.use_denoising = True
scene.cycles.max_bounces = 8
scene.cycles.transparent_max_bounces = 16
scene.cycles.caustics_reflective = False
scene.cycles.caustics_refractive = False
scene.cycles.sample_clamp_indirect = 8
w, h = (int(v) for v in args.res.lower().split('x'))
scene.render.resolution_x, scene.render.resolution_y = w, h
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
for vt in ('AgX', 'Filmic'):
    try:
        scene.view_settings.view_transform = vt
        break
    except TypeError:
        continue
for look in ('AgX - Medium High Contrast', 'Medium High Contrast'):
    try:
        scene.view_settings.look = look
        break
    except TypeError:
        continue


def aim(cam_ob, pos, tgt):
    cam_ob.location = P(*pos)
    cam_ob.rotation_euler = (P(*tgt) - P(*pos)).to_track_quat('-Z', 'Y').to_euler()


if args.blend:
    set_lighting(11, -23.44)
    aim(cam, VIEWS['front']['cam'], VIEWS['front']['tgt'])
    cam_data.lens = VIEWS['front']['lens']
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.blend))
    print('Saved', args.blend)

names = [] if args.views == 'none' else (list(VIEWS) if args.views == 'all' else args.views.split(','))
os.makedirs(args.out, exist_ok=True)
for n in names:
    v = VIEWS[n]
    aim(cam, v['cam'], v['tgt'])
    cam_data.lens = v['lens']
    cam_data.clip_start = 0.05
    set_lighting(v['hour'], v['decl'], v.get('night', False))
    scene.view_settings.exposure = v['exposure']
    scene.render.filepath = os.path.abspath(os.path.join(args.out, n + '.png'))
    bpy.ops.render.render(write_still=True)
    print('Rendered', scene.render.filepath)
