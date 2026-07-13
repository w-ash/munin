"""Entry point for ``python -m vault_scripts.research`` (the ``vault-tool research``
dispatcher target). Delegates to the argparse CLI in :mod:`cli`."""

from vault_scripts.research.cli import main

main()
