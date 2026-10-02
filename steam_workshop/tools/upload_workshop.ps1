# Публикация / обновление предмета Steam Workshop через SteamCMD.
# Запускается из upload_workshop.bat. Пароль НЕ хранится: SteamCMD спрашивает его и код Steam Guard сам.
#
#   upload_workshop.bat                       - интерактивно
#   upload_workshop.bat -Login myname         - логин без вопроса (или переменная STEAM_LOGIN)
#   upload_workshop.bat -DryRun               - только собрать и показать VDF, ничего не загружать
#   upload_workshop.bat -ChangeNote "текст" -Yes   - без вопросов (кроме пароля в SteamCMD)
param(
    [string]$Login = $env:STEAM_LOGIN,
    [string]$ChangeNote = "",
    [switch]$DryRun,
    [switch]$Yes
)
$ErrorActionPreference = "Stop"
$Utf8NoBom = New-Object System.Text.UTF8Encoding $false
$Root = Split-Path -Parent $PSScriptRoot            # папка steam_workshop
$TemplatePath = Join-Path $Root "workshop_item.vdf"
$DescPath = Join-Path $Root "workshop_description_ru.txt"
$ExpectedAppId = "1359980"
$MaxPreviewBytes = 1MB                               # лимит Steam на превью

function Fail([string]$msg) {
    Write-Host ""
    Write-Host "ОШИБКА: $msg" -ForegroundColor Red
    exit 1
}
function Has-NonAscii([string]$s) { return $s -match '[^\x00-\x7F]' }

# ---------- 1. SteamCMD ----------
function Find-SteamCmd {
    if ($env:STEAMCMD) {
        $p = $env:STEAMCMD
        if (Test-Path -LiteralPath $p -PathType Container) { $p = Join-Path $p "steamcmd.exe" }
        if (Test-Path -LiteralPath $p -PathType Leaf) { return (Resolve-Path -LiteralPath $p).Path }
        Write-Host "Переменная STEAMCMD указывает на несуществующий файл: $env:STEAMCMD" -ForegroundColor Yellow
    }
    $local = Join-Path $Root "steamcmd\steamcmd.exe"
    if (Test-Path -LiteralPath $local -PathType Leaf) { return $local }
    $cmd = Get-Command steamcmd -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}
$SteamCmd = Find-SteamCmd
if (-not $SteamCmd -and -not $DryRun) {
    Write-Host "SteamCMD не найден." -ForegroundColor Red
    Write-Host "Скачай официальный SteamCMD от Valve:"
    Write-Host "  https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
    Write-Host "  (описание: https://developer.valvesoftware.com/wiki/SteamCMD)"
    Write-Host "и распакуй steamcmd.exe в папку:"
    Write-Host "  $(Join-Path $Root 'steamcmd')"
    Write-Host "или укажи путь в переменной окружения STEAMCMD."
    exit 1
}

# ---------- 2. Шаблон VDF ----------
if (-not (Test-Path -LiteralPath $TemplatePath)) { Fail "Нет файла $TemplatePath" }
$template = [System.IO.File]::ReadAllText($TemplatePath, $Utf8NoBom)
$kv = @{}
foreach ($m in [regex]::Matches($template, '(?m)^\s*"(\w+)"\s+"((?:[^"\\]|\\.)*)"')) {
    $kv[$m.Groups[1].Value.ToLower()] = $m.Groups[2].Value
}
foreach ($k in "appid", "publishedfileid", "contentfolder", "previewfile", "visibility", "title", "description", "changenote") {
    if (-not $kv.ContainsKey($k)) { Fail "В workshop_item.vdf нет ключа `"$k`"" }
}
if ($kv["appid"] -ne $ExpectedAppId) { Fail "appid в VDF = $($kv['appid']), ожидается $ExpectedAppId (POSTAL: Brain Damaged)" }
if ($kv["publishedfileid"] -notmatch '^\d+$') { Fail "publishedfileid должен быть числом (0 для новой работы)" }
if ($kv["visibility"] -notmatch '^[0-3]$') { Fail "visibility должен быть 0..3" }
$PublishedId = $kv["publishedfileid"]
$IsNew = ($PublishedId -eq "0")
$VisNames = @{ "0" = "публичная"; "1" = "только друзья"; "2" = "скрытая (только ты)"; "3" = "по ссылке (unlisted)" }

function Resolve-InRoot([string]$p) {
    $p = $p -replace '\\\\', '\' -replace '/', '\'
    if (-not [System.IO.Path]::IsPathRooted($p)) { $p = Join-Path $Root $p }
    return [System.IO.Path]::GetFullPath($p)
}
$Content = Resolve-InRoot $kv["contentfolder"]
$Preview = Resolve-InRoot $kv["previewfile"]

# ---------- 3. Проверка контента и превью ----------
if (-not (Test-Path -LiteralPath $Content -PathType Container)) { Fail "Нет папки контента: $Content" }
if (-not (Test-Path -LiteralPath (Join-Path $Content "ru_patch.exe"))) {
    Fail "В $Content нет ru_patch.exe. Сначала запусти prepare_workshop.bat"
}
$files = Get-ChildItem -LiteralPath $Content -Recurse -File -Force
$junk = $files | Where-Object { $_.FullName -match '\\\.git(\\|$)|\.pdb$|\.spec$|\.pyc$|\.log$|\\build\\|ssfn|config\.vdf$' }
if ($junk) { Fail ("В папке контента лишние/служебные файлы:`n  " + (($junk | ForEach-Object { $_.FullName }) -join "`n  ")) }
if (-not (Test-Path -LiteralPath $Preview -PathType Leaf)) { Fail "Нет файла превью: $Preview" }
$pv = (Get-Item -LiteralPath $Preview).Length
if ($pv -gt $MaxPreviewBytes) { Fail ("Превью {0:N0} байт — больше лимита Steam 1 МБ" -f $pv) }

$Description = $kv["description"]
if (Test-Path -LiteralPath $DescPath) { $Description = [System.IO.File]::ReadAllText($DescPath, $Utf8NoBom).Trim() }
if ($Description.Length -gt 8000) { Fail "Описание длиннее 8000 символов (лимит Steam)" }

Write-Host ""
Write-Host "Предмет Мастерской POSTAL: Brain Damaged (appid $ExpectedAppId)" -ForegroundColor Cyan
Write-Host "  Режим:      " -NoNewline
if ($IsNew) { Write-Host "СОЗДАНИЕ новой работы" -ForegroundColor Yellow }
else { Write-Host "ОБНОВЛЕНИЕ работы $PublishedId" -ForegroundColor Green }
Write-Host "  Название:   $($kv['title'])"
Write-Host "  Видимость:  $($kv['visibility']) — $($VisNames[$kv['visibility']])"
Write-Host "  Контент:    $Content"
foreach ($f in $files) { Write-Host ("                {0}  ({1:N0} байт)" -f $f.FullName.Substring($Content.Length + 1), $f.Length) }
Write-Host ("  Превью:     {0}  ({1:N0} байт)" -f $Preview, $pv)
Write-Host "  Описание:   $($Description.Length) символов"

# ---------- 4. Changenote ----------
if (-not $ChangeNote) {
    $def = $kv["changenote"]
    if ($def -eq "CHANGENOTE_PLACEHOLDER") { $def = "" }
    $prompt = "Описание изменений (changenote)"
    if ($def) { $prompt += " [Enter = '$def']" }
    if ($Yes) { $ChangeNote = $def } else { $ChangeNote = Read-Host $prompt }
    if (-not $ChangeNote) { $ChangeNote = $def }
}
if (-not $ChangeNote) { Fail "Нужно описание изменений (changenote)" }

# ---------- 5. Логин ----------
if (-not $DryRun) {
    if (-not $Login) { $Login = Read-Host "Steam login (пароль спросит SteamCMD)" }
    $Login = $Login.Trim()
    if (-not $Login) { Fail "Не указан Steam login" }
    if ($Login -match '\s') { Fail "Логин не должен содержать пробелов" }
}

# ---------- 6. Временная копия, если в путях кириллица ----------
# SteamCMD плохо работает с не-ASCII путями — в этом случае копируем контент в C:\pbd_ws_stage
$BuildDir = Join-Path $Root "build"
$Stage = $null
if ((Has-NonAscii $Content) -or (Has-NonAscii $Preview) -or (Has-NonAscii $BuildDir)) {
    $Stage = Join-Path $env:SystemDrive "pbd_ws_stage"
    Write-Host "В путях есть не-ASCII символы — использую временную папку $Stage" -ForegroundColor Yellow
    if (Test-Path -LiteralPath $Stage) { Remove-Item -LiteralPath $Stage -Recurse -Force }
    New-Item -ItemType Directory -Path (Join-Path $Stage "content") -Force | Out-Null
    Copy-Item -Path (Join-Path $Content "*") -Destination (Join-Path $Stage "content") -Recurse -Force
    $newPreview = Join-Path $Stage ("preview" + [System.IO.Path]::GetExtension($Preview))
    Copy-Item -LiteralPath $Preview -Destination $newPreview -Force
    $Content = Join-Path $Stage "content"; $Preview = $newPreview; $BuildDir = $Stage
}

# ---------- 7. Сборка VDF для SteamCMD ----------
function Esc-Path([string]$p) { return ($p -replace '\\', '\\') }          # как в примере Valve: D:\\Content\\...
function Esc-Text([string]$s) { return ($s -replace '\\', '/' -replace '"', [string][char]0x201D) }   # без " и \ — их SteamCMD может разобрать как разметку VDF
$vdf = @"
"workshopitem"
{
	"appid"		"$ExpectedAppId"
	"publishedfileid"		"$PublishedId"
	"contentfolder"		"$(Esc-Path $Content)"
	"previewfile"		"$(Esc-Path $Preview)"
	"visibility"		"$($kv['visibility'])"
	"title"		"$(Esc-Text $kv['title'])"
	"description"		"$(Esc-Text $Description)"
	"changenote"		"$(Esc-Text $ChangeNote)"
}
"@
New-Item -ItemType Directory -Path $BuildDir -Force | Out-Null
$UploadVdf = Join-Path $BuildDir "upload.vdf"
[System.IO.File]::WriteAllText($UploadVdf, ($vdf -replace "`r`n", "`n"), $Utf8NoBom)
Write-Host "  VDF для SteamCMD: $UploadVdf"

if ($DryRun) {
    Write-Host ""
    Write-Host "DryRun: ничего не загружено. Собранный VDF:" -ForegroundColor Cyan
    Write-Host ([System.IO.File]::ReadAllText($UploadVdf, $Utf8NoBom))
    exit 0
}

if (-not $Yes) {
    $what = "Создать новую работу"
    if (-not $IsNew) { $what = "Обновить работу $PublishedId" }
    $ans = Read-Host "$what под аккаунтом '$Login'? (y/n)"
    if ($ans -notmatch '^(y|д|yes|да)$') { Write-Host "Отменено."; exit 1 }
}

# ---------- 8. Загрузка ----------
Write-Host ""
Write-Host "Запускаю SteamCMD: $SteamCmd" -ForegroundColor Cyan
Write-Host "SteamCMD сам спросит пароль и код Steam Guard. Первый запуск может обновлять SteamCMD пару минут."
Write-Host ""
& $SteamCmd +login $Login +workshop_build_item $UploadVdf +quit
$code = $LASTEXITCODE

# ---------- 9. Результат и запись ID ----------
$after = [System.IO.File]::ReadAllText($UploadVdf, $Utf8NoBom)
$m = [regex]::Match($after, '"publishedfileid"\s+"(\d+)"')
$NewId = if ($m.Success) { $m.Groups[1].Value } else { "0" }
if ($Stage) { Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction SilentlyContinue }
Write-Host ""
if ($IsNew -and $NewId -ne "0") {
    $t = [System.IO.File]::ReadAllText($TemplatePath, $Utf8NoBom)
    $t = [regex]::Replace($t, '("publishedfileid"\s+")0(")', "`${1}$NewId`${2}", 1)
    [System.IO.File]::WriteAllText($TemplatePath, $t, $Utf8NoBom)
    Write-Host "ГОТОВО: создана работа $NewId" -ForegroundColor Green
    Write-Host "ID записан в workshop_item.vdf — следующие запуски будут ОБНОВЛЯТЬ эту работу."
    Write-Host "Закоммить изменённый workshop_item.vdf, чтобы ID не потерялся."
    Write-Host "Страница: https://steamcommunity.com/sharedfiles/filedetails/?id=$NewId"
    exit 0
}
if (-not $IsNew -and $code -eq 0) {
    Write-Host "ГОТОВО: SteamCMD завершился без ошибок, работа $PublishedId обновлена." -ForegroundColor Green
    Write-Host "Проверь страницу: https://steamcommunity.com/sharedfiles/filedetails/?id=$PublishedId"
    exit 0
}
Write-Host "Загрузка НЕ подтверждена (код выхода SteamCMD: $code)." -ForegroundColor Red
Write-Host "Посмотри сообщения SteamCMD выше. Частые причины:"
Write-Host "  - неверный логин/пароль или код Steam Guard;"
Write-Host "  - 'Access Denied' / 'Failed to create': игра не принимает загрузки через SteamCMD или аккаунт не владеет игрой;"
Write-Host "  - нужно принять соглашение Мастерской: https://steamcommunity.com/sharedfiles/workshoplegalagreement"
exit 1
