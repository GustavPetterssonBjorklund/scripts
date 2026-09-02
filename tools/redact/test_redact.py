import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))

from redact import apply_redactions, detect_candidates  # noqa: E402


class EntraCredentialRedactionTest(unittest.TestCase):
    def test_standard_service_principal_environment_variables(self) -> None:
        text = (
            "AZURE_CLIENT_ID=11111111-2222-3333-4444-555555555555\n"
            "AZURE_CLIENT_SECRET=entra-secret-value-123\n"
            '"ENTRA_TENANT_ID"="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"\n'
        )

        candidates = detect_candidates(text, min_score=40)
        output = apply_redactions(text, candidates, [True] * len(candidates), "<redacted>")

        self.assertIn("AZURE_CLIENT_ID=<redacted>", output)
        self.assertIn("AZURE_CLIENT_SECRET=<redacted>", output)
        self.assertIn('"ENTRA_TENANT_ID"="<redacted>"', output)
        self.assertNotIn("11111111-2222-3333-4444-555555555555", output)
        self.assertNotIn("entra-secret-value-123", output)
        self.assertNotIn("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", output)


if __name__ == "__main__":
    unittest.main()
