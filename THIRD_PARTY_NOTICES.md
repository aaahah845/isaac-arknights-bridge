# Third-party components

No Arknights or Isaac game executable, game resource archive, account token,
Steam saved game, or developer profile is distributed in this package.
All game copies are made locally from the user's installed clients.

* Python 3.14: PSF license, runtime/LICENSE.txt and standard-library notices.
* PySide6/Shiboken/Qt: LGPL/GPL/commercial terms as provided by upstream;
  original dynamic libraries and dist-info/licenses are retained under
  runtime/Lib/site-packages. https://doc.qt.io/qtforpython-6/licenses.html
* Frida 17.9.1: wxWindows Library Licence 3.1 for core/Gadget and upstream
  third-party notices. https://github.com/frida/frida (see upstream COPYING).
* LIEF, Pillow and other Python dependencies: see their retained dist-info
  license directories. Dependency versions are in setup/requirements.lock.txt.
* REPENTOGON Launcher: GPL v2; unmodified launcher and required runtime data.
  License and source snapshot are under licenses/REPENTOGON-launcher-*. Source
  tag v0.4.9-beta (release asset SHA-256 7e4a45d8b9f099ea79e42f86bc24c2a05b35e239d7bc4d597c11b5bceaccfd6a), upstream
  https://github.com/TeamREPENTOGON/Launcher .
* OpenBachelorS and OpenBachelorC: downloaded from pinned upstream commits on
  first installation. Upstream licensing and the availability of readable
  sources must be assessed separately; no new license is asserted here.

This notice is informational and does not replace any component's license.
For public redistribution, retain the whole licenses directory and all
dependency license metadata. Do not include generated local-client folders.
