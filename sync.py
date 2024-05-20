#!/usr/bin/env python3
from livesync import Folder, sync

sync(Folder('.', 'penthouse.local:~/robot'))
