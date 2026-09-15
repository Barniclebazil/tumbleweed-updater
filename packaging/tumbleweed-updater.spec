#
# spec file for package tumbleweed-updater
#

Name:           tumbleweed-updater
Version:        0.7.0
Release:        0
Summary:        Tray-based update manager for openSUSE Tumbleweed on KDE
License:        GPL-3.0-or-later
URL:            https://github.com/Barniclebazil/tumbleweed-updater
Source0:        %{name}-%{version}.tar.xz
BuildArch:      noarch

BuildRequires:  python-rpm-macros
BuildRequires:  systemd-rpm-macros
BuildRequires:  hicolor-icon-theme

Requires:       python3-base
Requires:       python3-pyside6
Requires:       python3-pyte
Requires:       zypper
Requires:       polkit
Recommends:     polkit-kde-agent-6
Recommends:     flatpak
Recommends:     snapper-zypp-plugin
%{?systemd_ordering}

%description
Tumbleweed Updater lives in the system tray and follows the Plasma theme while
the system is current, turning orange when a distribution upgrade or Flatpak
updates are available. It runs "zypper dup" in an embedded terminal so the user
can answer the resolver's questions, and relies on snapper-zypp-plugin for the
pre/post Btrfs snapshots. A systemd timer checks for updates in the background;
the cadence is configurable from the app.

%prep
%autosetup -n %{name}-%{version}

%build
# Pure Python plus data files - nothing to compile.

%install
DESTDIR=%{buildroot} PREFIX=%{_prefix} SITELIB=%{python3_sitelib} \
    sh packaging/install.sh
%py3_compile %{buildroot}%{python3_sitelib}/tumbleweed_updater

%pre
%service_add_pre tumbleweed-updater-check.timer tumbleweed-updater-check.service

%post
%service_add_post tumbleweed-updater-check.timer tumbleweed-updater-check.service

%preun
%service_del_preun tumbleweed-updater-check.timer tumbleweed-updater-check.service

%postun
%service_del_postun tumbleweed-updater-check.timer tumbleweed-updater-check.service

%files
%license LICENSE
%doc README.md
%{_bindir}/tumbleweed-updater
%{_libexecdir}/tumbleweed-updater/
%{python3_sitelib}/tumbleweed_updater/
%{_datadir}/polkit-1/actions/org.opensuse.tumbleweedupdater.policy
%{_unitdir}/tumbleweed-updater-check.service
%{_unitdir}/tumbleweed-updater-check.timer
%{_prefix}/lib/systemd/system-preset/50-tumbleweed-updater.preset
%{_datadir}/icons/hicolor/scalable/apps/tumbleweed-updater.svg
%{_datadir}/tumbleweed-updater/
%{_datadir}/applications/org.opensuse.TumbleweedUpdater.desktop

%changelog
* Tue Sep 15 2026 Barrie O'Neill Williams <barrie.oneill.williams@gmail.com> - 0.7.0
- The window now returns to a clean state after an update: closing it to the tray clears the embedded terminal and collapses it, a new setting moves that to as soon as the update finishes or turns it off, and the log can be cleared on demand with the new Hide log button or the terminal's right-click Clear entry.

* Mon Sep 14 2026 Barrie O'Neill Williams <barrie.oneill.williams@gmail.com> - 0.6.0
- Security and reliability release: the single-instance socket moves out of /tmp, the status directory no longer inherits the caller's umask, the update helper validates its zypper options against an allow-list, snapshot rollback and delete move behind a polkit action that always prompts, Cancel can now stop a running upgrade, and Menu -> Quit no longer aborts an update without asking.

* Sun Sep 13 2026 Barrie O'Neill Williams <barrie.oneill.williams@gmail.com> - 0.5.0
- Add Menu -> About... (shows the installed version) and a Restart App notice when the app itself has been updated. Also fixed a test-isolation bug that could silently overwrite real user settings with test data.

* Sun Sep 13 2026 Barrie O'Neill Williams <barrie.oneill.williams@gmail.com> - 0.4.1
- Retry the update check automatically when zypper's package lock is held (e.g. by PackageKit after resuming from sleep), instead of failing until the next scheduled check.

* Fri Sep 11 2026 Barrie O'Neill Williams <barrie.oneill.williams@gmail.com> - 0.4.0
- Add a snapshot manager (Menu -> Snapshots...) to list, compare, roll back, and delete Btrfs snapshots, and fix the update window not always refreshing after a check completes.

* Fri Sep 11 2026 Barrie O'Neill Williams <barrie.oneill.williams@gmail.com> - 0.3.2
- Update list now follows the terminal appearance settings, and the launcher icon is now a shield.

* Fri Sep 11 2026 Barrie O'Neill Williams <barrie.oneill.williams@gmail.com> - 0.3.1
- User-facing README rewrite, shield as the default tray icon, and a single combined update-confirmation/password prompt.

* Thu Sep 10 2026 Barrie O'Neill Williams <barrie.oneill.williams@gmail.com> - 0.3.0
- Selectable tray icon; toggles for vendor change, unattended install, pre-download, cleanup; reboot choice

* Thu Sep 10 2026 Barrie O'Neill Williams <barrie.oneill.williams@gmail.com> - 0.2.1
- Sign published packages and repository metadata

* Thu Sep 10 2026 Barrie O'Neill Williams - 0.2.0
- Configurable embedded-terminal appearance: font, size, background and text
  colour (Settings -> Terminal appearance).
* Thu Sep 10 2026 Barrie O'Neill Williams - 0.1.0
- Initial package.
