{ lib, findutils, openvpn, sudo, writeShellApplication }:

writeShellApplication {
  name = "ovpntmp";

  runtimeInputs = [
    findutils
    openvpn
    sudo
  ];

  text = builtins.readFile ../tools/ovpntmp/ovpntmp.sh;

  meta = {
    description = "Choose and run a temporary OpenVPN config from Downloads";
    homepage = "https://github.com/GustavPetterssonBjorklund/scripts";
    mainProgram = "ovpntmp";
    platforms = lib.platforms.linux;
  };
}
