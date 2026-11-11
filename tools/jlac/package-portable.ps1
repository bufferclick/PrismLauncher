# Packages a portable JL build for Windows.
#
#   pwsh -NoProfile -File tools/jlac/package-portable.ps1
#
# Produces, in ./out:
#   JL-Windows-x64.zip   complete portable install (JL.exe + Qt runtime)
#   JL.exe               the launcher binary on its own
#
# cmake --install is used because it already deploys the Qt runtime
# (windeployqt) and the required VC++ DLLs next to the executable.

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "../..")
Push-Location $root
try {
    $buildDir = "build"
    $installDir = "out/JL-Windows-x64"
    $outDir = "out"

    if (-not (Test-Path $buildDir)) {
        throw "Build directory '$buildDir' not found. Run cmake --build first."
    }

    # Fresh install tree, portable component included (adds portable.txt).
    if (Test-Path $installDir) { Remove-Item -Recurse -Force $installDir }
    New-Item -ItemType Directory -Force -Path $installDir | Out-Null

    cmake --install $buildDir --config Release --prefix $installDir
    if ($LASTEXITCODE -ne 0) { throw "cmake --install failed" }

    cmake --install $buildDir --config Release --prefix $installDir --component portable
    if ($LASTEXITCODE -ne 0) { throw "portable component install failed" }

    # cmake's install tree may nest the binary under bin/; normalise it to the root
    # so the zip is "extract and double-click JL.exe".
    $nestedExe = Join-Path $installDir "bin/JL.exe"
    if (Test-Path $nestedExe) {
        Get-ChildItem (Join-Path $installDir "bin") | Move-Item -Destination $installDir -Force
        Remove-Item -Recurse -Force (Join-Path $installDir "bin")
    }

    $exe = Join-Path $installDir "JL.exe"
    if (-not (Test-Path $exe)) {
        throw "JL.exe was not produced at $exe"
    }

    # The self-updater is a separate executable that PrismExternalUpdater launches as
    # "<binary>_updater.exe" from the app directory. Without it the update check fails
    # with "Failed to start after 5 seconds", so make sure it is packaged and that the
    # error is loud at build time instead of at the user's first update check.
    $updater = Join-Path $installDir "JL_updater.exe"
    if (-not (Test-Path $updater)) {
        throw "JL_updater.exe was not produced next to JL.exe; auto-update would break"
    }

    # Keep the standalone exe honest: it is only useful with the rest of the tree.
    Copy-Item $updater (Join-Path $outDir "JL_updater.exe") -Force

    Copy-Item $exe (Join-Path $outDir "JL.exe") -Force

    $zip = Join-Path $outDir "JL-Windows-x64.zip"
    if (Test-Path $zip) { Remove-Item -Force $zip }
    Compress-Archive -Path (Join-Path $installDir "*") -DestinationPath $zip -CompressionLevel Optimal

    Get-ChildItem $outDir | Format-Table Name, Length
}
finally {
    Pop-Location
}
