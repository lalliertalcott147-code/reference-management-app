import sys

if "--runtime-probe" in sys.argv:
    sys.argv.remove("--runtime-probe")
    from catalyst_literature.runtime_probe import main
elif "--pdf-worker" in sys.argv:
    sys.argv.remove("--pdf-worker")
    from catalyst_literature.pdfs.worker import main
else:
    from catalyst_literature.diagnostics import main

raise SystemExit(main())
