{
  description = "Small CLI utilities packaged as a Nix flake";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
  };

  outputs = { self, nixpkgs }:
    let
      lib = nixpkgs.lib;
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = f: lib.genAttrs systems (system: f system);
    in
    {
      formatter = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        pkgs.nixfmt-rfc-style
      );

      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        rec {
          gitx = pkgs.callPackage ./pkgs/gitx.nix { };
          ovpntmp = pkgs.callPackage ./pkgs/ovpntmp.nix { };
          default = gitx;
        }
      );

      apps = forAllSystems (system:
        let
          packages = self.packages.${system};
          gitxApp = {
            type = "app";
            program = "${packages.gitx}/bin/gitx";
          };
          ovpntmpApp = {
            type = "app";
            program = "${packages.ovpntmp}/bin/ovpntmp";
          };
        in
        {
          gitx = gitxApp;
          ovpntmp = ovpntmpApp;
          default = gitxApp;
        }
      );

      checks = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          packages = self.packages.${system};
        in
        {
          inherit (packages) gitx ovpntmp;

          gitx-help = pkgs.runCommand "gitx-help" {
            nativeBuildInputs = [ packages.gitx ];
          } ''
            gitx -h > "$out"
          '';

          ovpntmp-syntax = pkgs.runCommand "ovpntmp-syntax" {
            nativeBuildInputs = [ pkgs.bash ];
          } ''
            bash -n ${./tools/ovpntmp/ovpntmp.sh}
            touch "$out"
          '';
        }
      );

      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [
              git
              nixfmt-rfc-style
              python3
              shellcheck
              shfmt
            ];
          };
        }
      );
    };
}
