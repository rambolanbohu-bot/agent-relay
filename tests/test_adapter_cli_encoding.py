import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "transport"))
import adapter


class TestAdapterCliEncoding(unittest.TestCase):
    def test_confirmed_send_receipt_prints_once_on_cp1252_stdout(self):
        receipt = {"ok": True, "delivery": "message_sent", "detail": "确认 🧪"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "message.txt"
            path.write_text("synthetic", encoding="utf-8")
            with io.TextIOWrapper(io.BytesIO(), encoding="cp1252") as stdout:
                with patch.object(adapter, "Adapter") as factory, redirect_stdout(stdout):
                    send = factory.return_value.send
                    send.return_value = receipt
                    status = adapter.main([
                        "--skill-root", directory, "send", "--text-file", str(path),
                    ])
                    send.assert_called_once_with("chatgpt", "synthetic", "")
                stdout.flush()
                self.assertEqual(json.loads(stdout.buffer.getvalue().decode("ascii")), receipt)
                self.assertEqual(status, 0)
