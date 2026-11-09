from core.config.settings import Config
from tui.app import JagAgentApp


def main():
    config = Config()
    app = JagAgentApp(config=config)
    app.run()


if __name__ == "__main__":
    main()
