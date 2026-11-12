from core.config.settings import Config
from core.logging_setup import setup_logging
from tui.app import JagAgentApp


def main():
    config = Config()
    log_path = setup_logging(config.get_log_path(), config.get_log_level())
    app = JagAgentApp(config=config)
    if log_path is not None:
        app.sub_title = f"{config.get_ui_sub_title()} · log: {log_path.name}"
    app.run()


if __name__ == "__main__":
    main()
