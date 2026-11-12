"""Manage businesses from the command line.

  python -m app.businesses list
  python -m app.businesses create "Rina's Sarees" [--slug rinas-sarees] [--demo]
  python -m app.businesses rename rinas-sarees "Rina Saree House"
  python -m app.businesses status rinas-sarees suspended
  python -m app.businesses delete rinas-sarees --yes
  python -m app.businesses plan rinas-sarees standard      (plans: free, standard, unlimited, or any the platform administrator made)
  python -m app.businesses rekey                           (re-encrypt older stored secrets under per-business keys; also done at startup)

Your existing install appears as the business "default" (its file is not moved). --demo fills a new business with the Northwind sample data.
"""
from __future__ import annotations

import sys

from . import db, registry


def _print_all() -> None:
    for b in registry.all_businesses():
        with db.business(b["id"]):
            n = db.get("SELECT COUNT(*) n FROM products")["n"]
            c = db.get("SELECT COUNT(*) n FROM conversations")["n"]
        print(f"{b['slug']:<24} {b['status']:<10} {b['name']:<30} products {n:<5} conversations {c:<5} {b['path']}")


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, args = argv[0], argv[1:]
    try:
        if cmd == "list":
            _print_all()
        elif cmd == "create":
            slug = args[args.index("--slug") + 1] if "--slug" in args else None
            names = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] != "--slug")]
            if not names:
                print("Give the business a name.")
                return 2
            b = registry.create(names[0], slug)
            if "--demo" in args:
                from . import seed
                with db.business(b["id"]):
                    seed.seed()
            print(f"Created {b['slug']} ({b['id']}) at {b['path']}")
        elif cmd == "rename":
            print(f"Renamed to {registry.rename(args[0], args[1])['name']}")
        elif cmd == "status":
            print(f"{args[0]} is now {registry.set_status(args[0], args[1])['status']}")
        elif cmd == "plan":
            print(f"{args[0]} is now on the {registry.plan_of(registry.set_plan(args[0], args[1])['id'])['name']} plan")
        elif cmd == "rekey":
            from . import secrets_store
            print(f"Re-encrypted {secrets_store.rekey_all()} stored secrets")
        elif cmd == "delete":
            if "--yes" not in args:
                print("This deletes the business and all its data for good. Run again with --yes to confirm.")
                return 2
            registry.delete(args[0])
            print(f"Deleted {args[0]}")
        else:
            print(__doc__)
            return 2
    except (registry.RegistryError, registry.UnknownBusiness, IndexError) as e:
        print(f"Error: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
