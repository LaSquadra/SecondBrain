from second_brain.core.interfaces import Notifier


class ConsoleNotifier(Notifier):
    def notify_filed(self, message: str) -> None:
        print(message)

    def notify_needs_review(self, message: str) -> None:
        print(message)

    def notify_digest(self, message: str) -> None:
        print(message)
