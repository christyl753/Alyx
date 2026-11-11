"""
Test de non-régression stricte : Éradication totale des mentions UQO / AGE-UQO
dans l'ensemble de l'application Alyx (R1, Feature 13).
"""

import os
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Extensions de fichiers applicatifs à auditer
AUDITED_EXTENSIONS = {
    ".cs", ".axaml", ".py", ".json", ".yaml", ".yml",
    ".ts", ".tsx", ".html", ".css", ".bat", ".sh", ".md",
    ".csproj", ".sln", ".props", ".targets", ".xml"
}

# Répertoires à exclure de l'audit (fichiers temporaires, venv, git, métadonnées agents)
EXCLUDED_DIRS = {
    ".git", ".venv", ".venv_stt", ".agents", "bin", "obj",
    "node_modules", "dist", "build", "__pycache__", ".pytest_cache"
}

# Fichiers de spécification où la mention UQO apparaît uniquement comme clause d'interdiction formelle
ALLOWED_CLAUSE_FILES = {
    "PROJECT.md", "ORIGINAL_REQUEST.md", "test_no_uqo_mentions.py"
}


class TestNoUqoMentions(unittest.TestCase):
    """Vérifie qu'aucune mention d'UQO ou AGE-UQO ne subsiste dans le code applicatif."""

    def test_zero_uqo_mentions_in_codebase(self):
        forbidden_patterns = ["uqo", "age-uqo"]
        violations = []

        for root, dirs, files in os.walk(PROJECT_ROOT):
            # Filtrer les répertoires exclus
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]

            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext not in AUDITED_EXTENSIONS:
                    continue

                if file in ALLOWED_CLAUSE_FILES:
                    continue

                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, PROJECT_ROOT)

                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        for line_num, line in enumerate(f, start=1):
                            line_lower = line.lower()
                            for pat in forbidden_patterns:
                                if pat in line_lower:
                                    violations.append(f"{rel_path}:{line_num} -> {line.strip()}")
                except Exception as ex:
                    self.fail(f"Erreur de lecture sur {rel_path}: {ex}")

        if violations:
            msg = f"Des mentions interdites d'UQO ont été trouvées ({len(violations)} occurrences) :\n"
            msg += "\n".join(violations[:20])
            self.fail(msg)


if __name__ == "__main__":
    unittest.main()
