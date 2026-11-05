"""Run the CADOS server: python -m opensketch [--port 8000] [--no-browser] [--supervise]

Recovery, run on the server itself (on Fly: fly ssh console -a cados -C "python -m opensketch --reset-password EMAIL"):
--reset-password EMAIL gives that account a new strong password, prints it once and signs the account out everywhere.
Whoever can run commands on the server can already read its data, so this needs no other password. It writes the
account files from a second process: run it while nobody is signing up or being changed on the Admin page."""

import argparse
import faulthandler
import signal
import sys
import threading
import webbrowser

import uvicorn


def main():
    ap = argparse.ArgumentParser(prog="opensketch")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true", help="do not open the home page in a web browser")
    ap.add_argument("--supervise", action="store_true",
                    help="run the server as a child process and restart it when it hangs or exits (hosting)")
    ap.add_argument("--reset-password", metavar="EMAIL", help="give this account a new password and print it (recovery)")
    args = ap.parse_args()
    if args.reset_password:
        sys.exit(reset_password(args.reset_password))
    if args.supervise:
        from . import supervisor
        sys.exit(supervisor.main(args.host, args.port))
    if hasattr(signal, "SIGUSR1"):  # kill -USR1 <pid> prints every thread's stack (the supervisor does it before a restart)
        faulthandler.register(signal.SIGUSR1, all_threads=True)
    from .cadworker import oom_score
    oom_score(-500)  # out of memory: the kernel takes a CAD worker or job first, not the server everyone uses
    url = f"http://{args.host}:{args.port}/"
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"CADOS running at {url}")
    # on a stop, open connections (the add-in's long polls) get 3 s to finish instead of holding the restart up
    uvicorn.run("opensketch.server:app", host=args.host, port=args.port, log_level="warning", timeout_graceful_shutdown=3)


def reset_password(email: str) -> int:
    from . import accounts, auth
    u = accounts.find_by_email(email)
    if u is None:
        print(f"No CADOS account has the email {email.strip().lower()}.", file=sys.stderr)
        return 1
    new = auth.suggest_password()
    accounts.set_password(u["id"], new, by="owner")
    print(f"New password for {u['email']}: {new}")
    print("Sign in with it, then choose your own in Settings. Every earlier sign-in of this account has ended.")
    return 0


if __name__ == "__main__":
    main()
