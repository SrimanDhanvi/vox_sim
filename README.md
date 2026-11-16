# Soft Material Simulator

A Python-based voxel simulation project for designing and testing magnetic soft material structures. The app includes a graphical editor for creating voxel layouts and a simulation runner that invokes the Voxelyze engine to evaluate physical behavior.

## Project overview

This project combines:

- a voxel-based design interface
- material property configuration
- magnetic field simulation support
- output analysis for deformation and performance

The main workflow is:

1. Create or load a voxel grid in the interface.
2. Choose materials and edit the structure.
3. Run simulation through the Voxelyze engine.
4. Inspect results such as displacement and fitness metrics.

## Repository structure

- `main.py` — graphical application entry point
- `sim_runner.py` — simulation orchestration and Voxelyze integration
- `requirements.txt` — Python dependencies
- `Soft Material Simulator.spec` — PyInstaller packaging configuration
- `voxelyze/` — bundled Voxelyze executable required by the simulator
- `sim_fig/` — generated simulation figure output (local/generated)
- `build/` and `dist/` — generated build artifacts (ignored by git)
- `venv/` — local Python virtual environment (ignored by git)

## Requirements

Python 3.10+ is recommended.

Install dependencies with:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Running the app

Start the project from the repository root:

```bash
python main.py
```

## Simulation backend

The project uses the Voxelyze simulator binary located in `voxelyze/voxelyze`. The simulation runner writes VXA and magnetic profile XML files, launches the engine, and parses the output fitness results.

## Notes

- This project is designed for local development and simulation execution.
- Generated folders such as `build/`, `dist/`, `__pycache__/`, and `venv/` should not be committed.
- The included `.gitignore` keeps local environment and build artifacts out of source control.

## License

This project does not currently include a license file. If you plan to share or distribute the code publicly, add an appropriate license before publishing.
