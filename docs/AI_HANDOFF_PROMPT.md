# Prompt for teammates using an AI coding assistant

Copy the prompt below into a new AI chat and replace the bracketed fields.

> We are Team 12 building an IoT mini-project called **Smart Production-Line
> Monitoring and Bottleneck Detection**. Work in the attached
> `team12-iot-project-ml-updated` project. The fixed source is Company A from
> HumanCenteredTechnology/SME-Manufacturing-Dataset at revision
> `0d37af3686a0508d38516cfc1220f4bba8ccc169`; do not substitute or alter
> the raw data. The CSV has independent machines but no verified route,
> queues, waiting times or line output. Keep real observed-machine findings,
> model forecasts and the virtual-line simulation explicitly separate.
>
> **My assigned workstream:** [data / IoT integration / analytics and ML /
> virtual line and control / presentation].
>
> **Specific change I need:** [describe one concrete change or bug].
>
> First read README.md, docs/ML_WORKFLOW.md, docs/ASSUMPTIONS.md,
> docs/TEAM_ROADMAP.md and the relevant source files. Explain what the
> current code actually does, then implement the requested change. Preserve
> the actual path: MQTT -> Node-RED validation -> SQLite -> validated
> MQTT -> rolling analytics and selected model -> forecast/advisory.
> Virtual-line commands go through MQTT to the virtual actuator. Do not invent bottleneck labels or claim that the
> virtual line's throughput gain happened in the factory. Keep thresholds
> in `config/config.yaml` when practical.
>
> Verify the change with `python tests/test_logic.py`; if it touches
> integration, run `python scripts/run_demo.py --once --speed 1000` and
> `python scripts/check_demo.py`. If it touches the virtual control rule,
> rerun `python src/scenario_compare.py`. Update affected docs and
> generated result files. Report the files changed, the exact commands
> run, observed results, and any remaining limitation. Ask for a missing
> assignment detail only if the repository cannot resolve it.


On Windows, use '.\.venv\Scripts\python.exe' in place of 'python' after running the setup script.
