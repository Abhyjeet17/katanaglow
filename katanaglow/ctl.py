"""katanaglow-ctl: command-line control of the running service."""
import argparse
import json
import sys

from . import client


def colours(text):
    return [c.lstrip("#").upper() for c in text.split(",") if c]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="katanaglow-ctl", description=__doc__)
    ap.add_argument("--socket", default=client.DEFAULT_SOCKET, help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show service status and current settings")
    sub.add_parser("off", help="turn the keyboard lighting off")
    p = sub.add_parser("static", help="one colour for all zones, or four (left block, centre, right block, numpad)")
    p.add_argument("colours", type=colours, help="FF0000 or FF0000,00FF00,0000FF,FFFFFF")
    for name in ("wave", "breathe", "ripple"):
        p = sub.add_parser(name, help=f"{name} effect")
        p.add_argument("palette", nargs="?", type=colours, help="comma list of colours, e.g. FF0040,00A0FF")
    for name, h in (("brightness", "0..1"), ("speed", "0.25..4"),
                    ("punch", "0..1 ripple contrast over a non-black resting colour")):
        p = sub.add_parser(name, help=h)
        p.add_argument("value", type=float)
    p = sub.add_parser("gain", help="colour balance R,G,B each 0..1, e.g. 1,0.8,0.7")
    p.add_argument("value", type=lambda t: [float(x) for x in t.split(",")])
    p = sub.add_parser("base", help="ripple resting colour")
    p.add_argument("value", type=lambda t: t.lstrip("#").upper())
    sub.add_parser("profiles", help="list saved profiles")
    p = sub.add_parser("profile", help="save, load or delete a named profile (colours, effect, speed, brightness)")
    p.add_argument("action", choices=("save", "load", "delete"))
    p.add_argument("name")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "status":
            st = client.request({"cmd": "status"}, args.socket)
            cfg = client.get(args.socket)["config"]
            print(json.dumps({"status": st["status"], "settings": cfg}, indent=2))
            return 0
        if args.cmd == "profiles":
            names = client.profiles(args.socket)
            print("\n".join(names) if names else "(no saved profiles)")
            return 0
        if args.cmd == "profile":
            if args.action == "save":
                client.save_profile(args.name, args.socket)
            elif args.action == "load":
                client.load_profile(args.name, args.socket)
            else:
                client.delete_profile(args.name, args.socket)
            done = {"save": "saved", "load": "loaded", "delete": "deleted"}[args.action]
            print(f"ok: profile {args.name!r} {done}")
            return 0
        if args.cmd == "off":
            patch = {"mode": "off"}
        elif args.cmd == "static":
            cs = args.colours
            if len(cs) == 1:
                cs = cs * 4
            patch = {"mode": "static", "zone_colours": cs}
        elif args.cmd in ("wave", "breathe", "ripple"):
            patch = {"mode": args.cmd}
            if args.palette:
                patch["palette"] = args.palette
        else:
            patch = {args.cmd: args.value}
        reply = client.set_config(patch, args.socket)
        print("ok: mode is", reply["config"]["mode"])
        return 0
    except client.ClientError as e:
        print("error:", e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
