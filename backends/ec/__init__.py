from conn import Connection, ConnectionFailedError
from packet import TagDict

__all__ = ["Connection", "ConnectionFailedError", "OperationFailedError", "TagDict"]

if __name__ == "__main__":
    import doctest
    import conn, packet, tag
    doctest.testmod(conn)
    doctest.testmod(packet)
    doctest.testmod(tag)
