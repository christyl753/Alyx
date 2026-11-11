Name:           alyx
Version:        0.1.0
Release:        1%{?dist}
Summary:        Sovereign AI Desktop Assistant

License:        MIT
URL:            https://github.com/christyl753/Alyx

Requires:       dotnet-runtime-8.0, python3, python3-pip

%description
Alyx is a 100% offline, local and private AI assistant with full system agency,
background automation, and neo-brutalist Avalonia desktop client.

%prep

%build

%install
mkdir -p %{buildroot}/opt/alyx
mkdir -p %{buildroot}/usr/bin
mkdir -p %{buildroot}/usr/share/applications

cat << 'EOF' > %{buildroot}/usr/bin/alyx
#!/usr/bin/env bash
exec /opt/alyx/bin/AlyxDesktop "$@"
EOF
chmod 755 %{buildroot}/usr/bin/alyx

cat << 'EOF' > %{buildroot}/usr/share/applications/alyx.desktop
[Desktop Entry]
Name=Alyx
Comment=Sovereign AI desktop companion
Exec=/usr/bin/alyx
Icon=alyx
Terminal=false
Type=Application
Categories=Utility;
EOF

%files
/opt/alyx
/usr/bin/alyx
/usr/share/applications/alyx.desktop

