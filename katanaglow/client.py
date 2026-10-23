"""Talk to the daemon over its control socket. Used by the CLI and the GUI."""
import json
import socket

DEFAULT_SOCKET = "/run/katanaglow/control.sock"
MAX_REPLY = 64 * 1024


class ClientError(Exception):
    pass


def request(payload, path=DEFAULT_SOCKET, timeout=3.0):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        try:
            s.connect(path)
        except FileNotFoundError:
            raise ClientError("the KatanaGlow service is not running (no control socket)")
        except PermissionError:
            raise ClientError("no permission to use the control socket; are you in the "
                              "'katanaglow' group? (log out and back in after installing)")
        except OSError as e:
            raise ClientError(f"cannot reach the service: {e}")
        s.sendall(json.dumps(payload).encode() + b"\n")
        buf = b""
        while b"\n" not in buf and len(buf) < MAX_REPLY:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
    except socket.timeout:
        raise ClientError("the service did not answer in time")
    finally:
        s.close()
    try:
        reply = json.loads(buf.split(b"\n", 1)[0])
    except ValueError:
        raise ClientError("unreadable reply from the service")
    if not reply.get("ok"):
        raise ClientError(reply.get("error", "request failed"))
    return reply


def get(path=DEFAULT_SOCKET):
    return request({"cmd": "get"}, path)


def set_config(patch, path=DEFAULT_SOCKET):
    return request({"cmd": "set", "config": patch}, path)


def profiles(path=DEFAULT_SOCKET):
    return request({"cmd": "profiles"}, path)["profiles"]


def save_profile(name, path=DEFAULT_SOCKET):
    return request({"cmd": "save_profile", "name": name}, path)["profiles"]


def load_profile(name, path=DEFAULT_SOCKET):
    return request({"cmd": "load_profile", "name": name}, path)


def delete_profile(name, path=DEFAULT_SOCKET):
    return request({"cmd": "delete_profile", "name": name}, path)["profiles"]
