# Builds sample-app into a signed debug APK with no Gradle — just the SDK
# build-tools + a JDK. Run from the repo root or this folder.
# Native tools (keytool, aapt2, javac) write progress to stderr; under a Stop
# preference PowerShell turns that into a terminating error. Use explicit
# $LASTEXITCODE checks after each step instead.
$ErrorActionPreference = "Continue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

$SDK = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { "C:\Android\sdk" }
$BT = Join-Path $SDK "build-tools\34.0.0"
$ANDROID_JAR = Join-Path $SDK "platforms\android-34\android.jar"
$aapt2 = Join-Path $BT "aapt2.exe"
$zipalign = Join-Path $BT "zipalign.exe"
$apksigner = Join-Path $BT "apksigner.bat"

# `jar` is not on PATH via the Oracle javapath shim; resolve it from the real
# JDK bin by following the javac symlink, with common install dirs as fallback.
$jar = $null
$javacSrc = (Get-Command javac -ErrorAction SilentlyContinue).Source
if ($javacSrc) {
    $tgt = (Get-Item $javacSrc).Target
    $realBin = if ($tgt) { Split-Path -Parent $tgt } else { Split-Path -Parent $javacSrc }
    $cand = Join-Path $realBin "jar.exe"
    if (Test-Path $cand) { $jar = $cand }
}
if (-not $jar) {
    $jar = (Get-ChildItem "C:\Program Files\Java\*\bin\jar.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1).FullName
}
if (-not $jar -or -not (Test-Path $jar)) { throw "jar.exe not found" }
$keytool = Join-Path (Split-Path -Parent $jar) "keytool.exe"
if (-not (Test-Path $keytool)) { throw "keytool.exe not found" }

$build = Join-Path $here "build"
if (Test-Path $build) { Remove-Item -Recurse -Force $build }
New-Item -ItemType Directory -Force -Path "$build\gen","$build\classes","$build\dex" | Out-Null

Write-Host "1/7 aapt2 compile resources"
& $aapt2 compile --dir res -o "$build\res.zip"
if ($LASTEXITCODE) { throw "aapt2 compile failed" }

Write-Host "2/7 aapt2 link"
& $aapt2 link -o "$build\base.apk" -I $ANDROID_JAR --manifest AndroidManifest.xml `
    --java "$build\gen" "$build\res.zip"
if ($LASTEXITCODE) { throw "aapt2 link failed" }

Write-Host "3/7 javac"
$javas = @("java\com\example\shop\MainActivity.java", "$build\gen\com\example\shop\R.java")
& javac --release 11 -classpath $ANDROID_JAR -d "$build\classes" $javas
if ($LASTEXITCODE) { throw "javac failed" }

Write-Host "4/7 jar + d8 (dex)"
& $jar cf "$build\classes.jar" -C "$build\classes" .
if ($LASTEXITCODE) { throw "jar failed" }
& (Join-Path $BT "d8.bat") --release --lib $ANDROID_JAR --output "$build\dex" "$build\classes.jar"
if ($LASTEXITCODE) { throw "d8 failed" }

Write-Host "5/7 add classes.dex into apk"
Copy-Item "$build\base.apk" "$build\app-unsigned.apk" -Force
& $jar uf "$build\app-unsigned.apk" -C "$build\dex" classes.dex
if ($LASTEXITCODE) { throw "adding dex failed" }

Write-Host "6/7 zipalign"
& $zipalign -f -p 4 "$build\app-unsigned.apk" "$build\app-aligned.apk"
if ($LASTEXITCODE) { throw "zipalign failed" }

Write-Host "7/7 sign"
$ks = "$build\debug.keystore"
& $keytool -genkeypair -keystore $ks -storepass android -keypass android `
    -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 `
    -dname "CN=Android Debug,O=Android,C=US" 2>&1 | Out-Null
& $apksigner sign --ks $ks --ks-pass pass:android --key-pass pass:android `
    --out "$build\shop-login.apk" "$build\app-aligned.apk"
if ($LASTEXITCODE) { throw "apksigner failed" }

& $apksigner verify --print-certs "$build\shop-login.apk" | Select-Object -First 1
Write-Host ("APK: " + (Join-Path $build "shop-login.apk"))
