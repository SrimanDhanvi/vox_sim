#!/usr/bin/env python3
"""
sim_runner.py
=============
Runs the Voxelyze simulator directly with a custom voxel grid.
Called from ui.py — does not modify beam_simulator.py at all.

USAGE (from ui.py):
    from sim_runner import run_voxelyze
    result = run_voxelyze(grid=grid, N_X=20, N_Y=20, B_mT=30.0)
    print(result['tip_deflection'])
"""

import os
import math
import time
import shutil
import sys
import stat   
import subprocess as sub
import numpy as np

# ── Paths ──────────────────────────────────────────────────────
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    _HERE = sys._MEIPASS
    # When PyInstaller bundles "voxelyze:voxelyze", it creates a nested path
    VOXELYZE_BIN = os.path.join(_HERE, "voxelyze", "voxelyze")
else:
    _HERE = os.path.dirname(os.path.abspath(__file__))
    VOXELYZE_BIN = os.path.join(_HERE, "voxelyze", "voxelyze")


# ── Linux Binary Permission Fix ───────────────────────────────
if os.path.exists(VOXELYZE_BIN):
    current_mode = os.stat(VOXELYZE_BIN).st_mode
    os.chmod(VOXELYZE_BIN, current_mode | stat.S_IEXEC)


# Short fixed work dir — avoids Voxelyze C path buffer limits
WORK_DIR_BASE = os.path.join(os.path.expanduser("~"), "vox_tmp") 

# ── Default material properties (same as beam_simulator.py) ───
LATTICE_DIM     = 200e-6
ELASTIC_MOD     = 150e3
DENSITY         = 2.41e3
POISSONS        = 0.4
M_PER_VOL       = 20e3
SIM_TIME        = 3.0
DT_FRAC         = 0.9
KIN_E_THRESHOLD = 1e-15
DAMPING_BOND_Z  = 1.0
COL_BOND_Z      = 0.8
SLOW_BOND_Z     = 0.01
GRAVITY_ENABLED = 0
IS_MAG_FORCE_ON = 1


def _write_vxa(vxa_path, fitness_path, qhull_path, curv_path,
               grid, N_X, N_Y, N_Z, materials=None):
    with open(vxa_path, "w") as f:
        # 1. Mandatory XML Header and Simulator Settings
        f.write('<?xml version="1.0" encoding="ISO-8859-1"?>\n')
        f.write('<VXA Version="1.0">\n')
        f.write('<Simulator>\n')
        f.write(f'<Integration><Integrator>0</Integrator><DtFrac>{DT_FRAC}</DtFrac></Integration>\n')
        f.write(f'<Damping><BondDampingZ>{DAMPING_BOND_Z}</BondDampingZ><ColDampingZ>{COL_BOND_Z}</ColDampingZ><SlowDampingZ>{SLOW_BOND_Z}</SlowDampingZ></Damping>\n')
        f.write('<Collisions><SelfColEnabled>0</SelfColEnabled><ColSystem>3</ColSystem><CollisionHorizon>2</CollisionHorizon></Collisions>\n')
        f.write('<Features><FluidDampEnabled>0</FluidDampEnabled><PoissonKickBackEnabled>0</PoissonKickBackEnabled><EnforceLatticeEnabled>0</EnforceLatticeEnabled></Features>\n')
        f.write('<SurfMesh><CMesh><DrawSmooth>1</DrawSmooth><Vertices/><Facets/><Lines/></CMesh></SurfMesh>\n')
        f.write(f'<StopCondition><StopConditionType>2</StopConditionType><StopConditionValue>{SIM_TIME}</StopConditionValue><AfterlifeTime>0</AfterlifeTime><MidLifeFreezeTime>0</MidLifeFreezeTime><InitCmTime>0</InitCmTime></StopCondition>\n')
        f.write('<EquilibriumMode><EquilibriumModeEnabled>1</EquilibriumModeEnabled></EquilibriumMode>\n')
        f.write(f'<GA><WriteFitnessFile>1</WriteFitnessFile><FitnessFileName>{fitness_path}</FitnessFileName><QhullTmpFile>{qhull_path}</QhullTmpFile><CurvaturesTmpFile>{curv_path}</CurvaturesTmpFile></GA>\n')
        f.write('</Simulator>\n')

        # 2. Environment & Boundary Conditions (Clamping the left side)
        f.write('<Environment>\n')
        f.write('<Fixed_Regions><NumFixed>0</NumFixed></Fixed_Regions>\n')
        f.write('<Forced_Regions><NumForced>0</NumForced></Forced_Regions>\n')
        f.write('<Boundary_Conditions>\n<NumBCs>1</NumBCs>\n<FRegion>\n<PrimType>0</PrimType>\n'
                '<X>0</X><Y>0</Y><Z>0</Z>\n'
                '<dX>0.01</dX><dY>1</dY><dZ>1</dZ>\n'
                '<Radius>0</Radius><R>0.4</R><G>0.6</G><B>0.4</B><alpha>1</alpha>\n'
                '<DofFixed>63</DofFixed>\n'
                '</FRegion>\n</Boundary_Conditions>\n')
        f.write(f'<Gravity><GravEnabled>{GRAVITY_ENABLED}</GravEnabled><GravAcc>-9.81</GravAcc><FloorEnabled>0</FloorEnabled></Gravity>\n')
        f.write('<Thermal><TempEnabled>0</TempEnabled></Thermal>\n')
        f.write('</Environment>\n')

        # 3. VXC Section (Lattice and Palette)
        f.write('<VXC Version="0.93">\n')
        f.write(f'<Lattice><Lattice_Dim>{LATTICE_DIM}</Lattice_Dim><X_Dim_Adj>1</X_Dim_Adj><Y_Dim_Adj>1</Y_Dim_Adj><Z_Dim_Adj>1</Z_Dim_Adj></Lattice>\n')
        f.write('<Voxel><Vox_Name>BOX</Vox_Name><X_Squeeze>1</X_Squeeze><Y_Squeeze>1</Y_Squeeze><Z_Squeeze>1</Z_Squeeze></Voxel>\n')

        f.write('<Palette>\n')
        if materials:
            for name, props in materials.items():
                mid = props['id']
                # Remove spaces/parentheses for Voxelyze safety
                safe_name = name.replace(" ", "_").replace("(", "").replace(")", "")
                hex_c = props.get('color', '#4a90d9')
                r = int(hex_c[1:3], 16) / 255
                g = int(hex_c[3:5], 16) / 255
                b = int(hex_c[5:7], 16) / 255
                f.write(f'<Material ID="{mid}">\n'
                        f'<MatType>0</MatType>\n<Name>{safe_name}</Name>\n'
                        f'<Display><Red>{r:.3f}</Red><Green>{g:.3f}</Green><Blue>{b:.3f}</Blue><Alpha>1.0</Alpha></Display>\n'
                        f'<Mechanical>\n<MatModel>0</MatModel>\n<Elastic_Mod>{props["ELASTIC_MOD"]}</Elastic_Mod>\n'
                        f'<Density>{props["DENSITY"]}</Density>\n<Poissons_Ratio>{props["POISSONS"]}</Poissons_Ratio>\n'
                        f'<uStatic>1.0</uStatic><uDynamic>0.5</uDynamic>\n</Mechanical>\n'
                    f'<Magnetic><M_per_vol>{props["M_PER_VOL"]}</M_per_vol><M_X>0.0</M_X><M_Y>0.0</M_Y><M_Z>1.0</M_Z></Magnetic>\n'
                        f'</Material>\n')
        f.write('</Palette>\n')

        # 4. Structure Section (Assigning materials to the grid)
        f.write(f'<Structure Compression="ASCII_READABLE">\n'
                f'<X_Voxels>{N_X}</X_Voxels>\n'
                f'<Y_Voxels>{N_Y}</Y_Voxels>\n'
                f'<Z_Voxels>{N_Z}</Z_Voxels>\n'
                f'<Data>\n')
        for _z in range(N_Z):
            f.write('<Layer><![CDATA[')
            for _y in range(N_Y):
                for _x in range(N_X):
                    f.write(str(int(grid[_y, _x])))
            f.write(']]></Layer>\n')
        f.write('</Data>\n</Structure>\n')
        
        f.write('</VXC>\n</VXA>\n')


def _write_m_xml(m_xml_path, B_magnitude, grid, N_X, N_Y, N_Z,
                 B_direction=(0, 0, 1), mag_grid=None):
    """Write per-voxel magnetisation.
    mag_grid: dict (ix,iy) → (Mx,My,Mz) for custom voxels.
    """
    Bx, By, Bz = B_direction
    # If no custom magnetisation is set, the unassigned voxels are aligned with the .
    def_mx, def_my, def_mz = 0.0, 0.0, 0.0

    with open(m_xml_path, "w") as f:
        f.write('<?xml version="1.0" encoding="ISO-8859-1"?>\n')
        f.write('<VoxelMProfile Version="1.0">\n')
        f.write('<ControllerType>quasi-static</ControllerType>\n')
        f.write(f'<StaticBMag>{abs(B_magnitude)}</StaticBMag>\n')
        f.write(f'<StaticBx>{Bx}</StaticBx>\n')
        f.write(f'<StaticBy>{By}</StaticBy>\n')
        f.write(f'<StaticBz>{Bz}</StaticBz>\n')
        f.write(f'<MperVol>{M_PER_VOL}</MperVol>\n')
        f.write(f'<KinEThreshold>{KIN_E_THRESHOLD}</KinEThreshold>\n')
        f.write(f'<IsMagForceOn>{IS_MAG_FORCE_ON}</IsMagForceOn>\n')
        f.write('<SavePosition>1</SavePosition>\n')
        f.write('<SaveOrientation>0</SaveOrientation>\n')
        f.write('<SaveVelocity>0</SaveVelocity>\n')
        f.write('<SaveAngVel>0</SaveAngVel>\n')
        f.write('<SaveStrainEnergy>0</SaveStrainEnergy>\n')
        f.write('<SaveKineticEnergy>0</SaveKineticEnergy>\n')
        f.write('<SavePressure>0</SavePressure>\n')
        f.write('<SaveForce>0</SaveForce>\n')
        f.write('<CaseMaxCOMZPos>0</CaseMaxCOMZPos>\n')
        f.write('<CaseMaxMinPosZ>0</CaseMaxMinPosZ>\n')
        f.write('<Is3D>0</Is3D>\n')
        f.write('<IsRecordVideo>0</IsRecordVideo>\n')
        f.write('<IsCreateHistory>0</IsCreateHistory>\n')
        f.write('<HistoryBW>1</HistoryBW>\n')
        f.write('<VideoBW>1</VideoBW>\n')
        f.write('<VoxelMagnetizations>\n')

        vox_idx = 0
        for z in range(N_Z):
            for y in range(N_Y):
                for x in range(N_X):
                    if grid[y, x] != 0:
                        # ── Use custom mag if set, else default ──
                        if mag_grid and (x, y) in mag_grid:
                            entry = mag_grid[(x, y)]
                            Mx, My, Mz = entry[0], entry[1], entry[2]
                            vox_m = entry[3] if len(entry) == 4 else M_PER_VOL
                        else:
                            Mx, My, Mz = def_mx, def_my, def_mz
                            vox_m = M_PER_VOL

                        f.write(f'<VoxelNum{vox_idx}>\n'
                                f'<VoxelMpervol>{vox_m}</VoxelMpervol>\n'
                                f'<VoxelMx>{Mx}</VoxelMx>\n'
                                f'<VoxelMy>{My}</VoxelMy>\n'
                                f'<VoxelMz>{Mz}</VoxelMz>\n'
                                f'</VoxelNum{vox_idx}>\n')
                        vox_idx += 1

        f.write('</VoxelMagnetizations>\n')
        f.write('</VoxelMProfile>\n')

def _parse_positions(fitness_path, n_voxels):
    """
    Parse voxel positions — handles both node-based (8 per voxel)
    and voxel-center-based output from different Voxelyze versions.
    """
    tag     = "<Voxel "
    tag_num = tag + "num: >"
    tag_x   = tag + "x: >"
    tag_y   = tag + "y: >"
    tag_z   = tag + "z: >"

    raw = {}   # vox_num → [x, y, z]
    vox_num = None

    try:
        with open(fitness_path) as fh:
            for line in fh:
                if tag_num in line:
                    vox_num = int(line[line.find(tag_num) + len(tag_num):
                                       line.find("</" + tag_num[1:])])
                    if vox_num not in raw:
                        raw[vox_num] = [np.nan, np.nan, np.nan]
                elif tag_x in line and vox_num is not None:
                    raw[vox_num][0] = float(
                        line[line.find(tag_x) + len(tag_x):
                             line.find("</" + tag_x[1:])])
                elif tag_y in line and vox_num is not None:
                    raw[vox_num][1] = float(
                        line[line.find(tag_y) + len(tag_y):
                             line.find("</" + tag_y[1:])])
                elif tag_z in line and vox_num is not None:
                    raw[vox_num][2] = float(
                        line[line.find(tag_z) + len(tag_z):
                             line.find("</" + tag_z[1:])])
    except Exception as e:
        print(f"Warning: position parsing failed: {e}")

    if not raw:
        return np.full((n_voxels, 3), np.nan)

    n_total = max(raw.keys()) + 1
    print(f"[parse] n_voxels={n_voxels}, max vox_num={n_total-1}")

    # ── Detect output mode ────────────────────────────────────
    if n_total <= n_voxels:
        # Voxelyze output voxel centers directly
        print("[parse] mode: voxel centers")
        positions = np.full((n_voxels, 3), np.nan)
        for idx, xyz in raw.items():
            if idx < n_voxels:
                positions[idx] = xyz
        return positions

    elif n_total <= n_voxels * 8 + 8:
        # Voxelyze output nodes (8 per voxel)
        print("[parse] mode: 8 nodes per voxel → averaging")
        n_nodes   = n_voxels * 8
        node_pos  = np.full((n_nodes, 3), np.nan)
        for idx, xyz in raw.items():
            if idx < n_nodes:
                node_pos[idx] = xyz
        # Average 8 nodes → 1 voxel center
        voxel_centers = np.full((n_voxels, 3), np.nan)
        for v in range(n_voxels):
            chunk = node_pos[v*8 : v*8+8]
            valid = chunk[~np.isnan(chunk[:, 0])]
            if len(valid) > 0:
                voxel_centers[v] = np.mean(valid, axis=0)
        return voxel_centers

    else:
        # Unknown mode — return raw averaged
        print(f"[parse] mode: unknown (n_total={n_total}) — using raw mean")
        all_vals = np.array([v for v in raw.values()])
        positions = np.full((n_voxels, 3), np.nan)
        # Best guess: chunk into n_voxels groups
        chunk_size = max(1, n_total // n_voxels)
        for v in range(n_voxels):
            chunk = all_vals[v*chunk_size : v*chunk_size+chunk_size]
            valid = chunk[~np.isnan(chunk[:, 0])]
            if len(valid) > 0:
                positions[v] = np.mean(valid, axis=0)
        return positions


def _build_initial_positions(grid, N_X, N_Y, N_Z, lattice_dim):
    """
    Rebuild undeformed voxel-center positions in exact Voxelyze write order.
    Must match the z→y→x loop order used in _write_m_xml.
    """
    initial = []
    for z in range(N_Z):
        for y in range(N_Y):
            for x in range(N_X):
                if grid[y, x] != 0:
                    initial.append([
                        (x + 0.5) * lattice_dim,
                        (y + 0.5) * lattice_dim,
                        (z + 0.5) * lattice_dim,
                    ])
    return np.array(initial, dtype=float)


def run_voxelyze(grid, N_X, N_Y, B_mT, N_Z=1, materials=None, B_direction=(0, 0, 1), mag_grid=None, timeout=120, debug=False):
    """
    Run Voxelyze simulation with a custom grid.

    Parameters
    ----------
    grid  : np.ndarray (N_Y, N_X) — 1=filled, 0=empty
    N_X   : int — grid width
    N_Y   : int — grid height
    B_mT  : float — magnetic field in mT
    N_Z   : int — grid depth (default 1)

    Returns
    -------
    dict with tip_deflection, z_displacements, x_positions, z_positions
    """
    if not os.path.isfile(VOXELYZE_BIN):
        raise FileNotFoundError(f"Voxelyze binary not found at: {VOXELYZE_BIN}")

    if materials is None:
        materials = {
            'MagSoElas_default': {
                'id': 1,
                'color': '#4a90d9',
                'LATTICE_DIM': LATTICE_DIM,
                'ELASTIC_MOD': ELASTIC_MOD,
                'DENSITY': DENSITY,
                'POISSONS': POISSONS,
                'M_PER_VOL': M_PER_VOL,
            }
        }

    B_magnitude  = B_mT * 1e-3
    n_voxels    = int(np.sum(grid != 0)) * N_Z  # only count filled voxels

    if n_voxels == 0:
        raise ValueError("No voxels are filled! Paint some voxels first.")

    work_dir = WORK_DIR_BASE
    os.makedirs(os.path.join(work_dir, "voxelyzeFiles"), exist_ok=True)
    os.makedirs(os.path.join(work_dir, "fitnessFiles"),  exist_ok=True)
    os.makedirs(os.path.join(work_dir, "tempFiles"),     exist_ok=True)

    run_name     = "sim"
    ind_id       = "00000"
    vxa_path     = os.path.join(work_dir, "voxelyzeFiles", f"{run_name}--id_{ind_id}.vxa")
    m_xml_path   = os.path.join(work_dir, "voxelyzeFiles", f"{run_name}--id_{ind_id}_M.xml")
    fitness_path = os.path.join(work_dir, "fitnessFiles",  f"{run_name}--id_{ind_id}.xml")
    qhull_path   = os.path.join(work_dir, "tempFiles", "qhull.txt")
    curv_path    = os.path.join(work_dir, "tempFiles", "curv.txt")

    if os.path.isfile(fitness_path):
        os.remove(fitness_path)

    try:
        _write_vxa(vxa_path, fitness_path, qhull_path, curv_path,
               grid, N_X, N_Y, N_Z, materials=materials)
        _write_m_xml(m_xml_path, B_magnitude, grid, N_X, N_Y, N_Z,
                 B_direction=B_direction, mag_grid=mag_grid)

        # # Temporarily add this to check the vxa file
        # with open(vxa_path, 'r') as f:
        #     print(f.read())

        cmd = f"{VOXELYZE_BIN} -f {vxa_path} -m {m_xml_path}"
        proc = sub.Popen(cmd, shell=True, cwd=_HERE,
                         stdout=sub.PIPE, stderr=sub.PIPE)

        elapsed   = 0.0
        timed_out = True
        while elapsed < timeout:
            if proc.poll() is not None:
                timed_out = False
                break
            # Also check if output file appeared
            if os.path.isfile(fitness_path) and os.path.getsize(fitness_path) > 0:
                time.sleep(0.3)  # let voxelyze finish writing
                timed_out = False
                break
            time.sleep(0.25)
            elapsed += 0.25

        try:
            stdout_b, stderr_b = proc.communicate(timeout=3)
        except sub.TimeoutExpired:
            proc.kill()
            stdout_b, stderr_b = proc.communicate()

        if debug:
            print(stdout_b.decode(errors='replace'))
            print(stderr_b.decode(errors='replace'))

        if timed_out:
            raise TimeoutError(f"Simulation timed out after {timeout}s")

        if not os.path.isfile(fitness_path) or os.path.getsize(fitness_path) == 0:
            raise RuntimeError("Voxelyze finished but output file is empty.")

# ── Parse results ──────────────────────────────────────
        positions = _parse_positions(fitness_path, n_voxels)
        valid_mask = ~np.isnan(positions[:, 0])
        valid = positions[valid_mask]
        
        # Check if we actually got any data back
        if len(valid) == 0:
            raise RuntimeError("Simulation finished, but no valid voxel positions were found in the output.")

        initial_positions = _build_initial_positions(
            grid, N_X, N_Y, N_Z, LATTICE_DIM)
        initial_valid = initial_positions[valid_mask]

        if len(initial_valid) != len(valid):
            raise RuntimeError("Parsed output size does not match initial voxel map.")

        displacements = valid - initial_valid
        disp_norms = np.linalg.norm(displacements, axis=1)
        max_displacement = float(np.max(disp_norms))

        com_before = np.mean(initial_valid, axis=0)
        com_after = np.mean(valid, axis=0)
        com_displacement_vec = com_after - com_before
        com_displacement = float(np.linalg.norm(com_displacement_vec))

        # Legacy tip metric retained for backward compatibility:
        # average z-displacement of voxels at the maximum initial x edge.
        x_max = float(np.max(initial_valid[:, 0]))
        x_tol = 0.5 * LATTICE_DIM
        tip_mask = initial_valid[:, 0] >= (x_max - x_tol)
        if not np.any(tip_mask):
            tip_mask[np.argmax(initial_valid[:, 0])] = True

        tip_deflection = float(np.mean(displacements[tip_mask, 2]))
        tip_deflection_y = float(np.mean(displacements[tip_mask, 1]))

        sorted_by_x = valid[valid[:, 0].argsort()]
        z_positions = sorted_by_x[:, 2]
        x_positions = sorted_by_x[:, 0]
        z_displacements = z_positions - z_positions[0]

        return {
            'tip_deflection':  tip_deflection,
            'z_displacements': z_displacements,
            'x_positions':     x_positions,
            'z_positions':     z_positions,
            'all_positions':   valid,
            'initial_positions': initial_valid,
            'displacements': displacements,
            'metrics': {
                'max_displacement': max_displacement,
                'com_displacement': com_displacement,
                'com_displacement_vec': com_displacement_vec,
                'tip_deflection_z': tip_deflection,
                'tip_deflection_y': tip_deflection_y,
                'tip_region_voxels': int(np.sum(tip_mask)),
            },
        }

    finally:
        if not debug:
            shutil.rmtree(work_dir, ignore_errors=True)