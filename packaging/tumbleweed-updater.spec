#
# spec file for package tumbleweed-updater
#

Name:           tumbleweed-updater
Version:        0.3.1
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
