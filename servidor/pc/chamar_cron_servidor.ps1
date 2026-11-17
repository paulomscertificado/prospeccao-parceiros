# Versao do dados\chamar_cron.ps1 para DEPOIS da virada para o servidor da Hostinger (docs\migracao-hostinger.md).
# Na virada, este arquivo e copiado por cima de dados\chamar_cron.ps1; a tarefa do Agendador continua a mesma.
# O que muda em relacao a versao da Vercel:
# - o WhatsApp Leads NAO e mais religado neste computador (ele roda no servidor; dois ligados = mesmo numero em dois lugares);
# - as copias de seguranca sao feitas no servidor; aqui so baixamos as de cada dia e mandamos para o Google Drive;
# - o relogio do sistema roda no proprio servidor a cada minuto; este computador so chama de reserva (?reserva=1).
# Le SITE, CRON_SECRET e SERVIDOR_IP de dados\agendador.txt e guarda o resultado em dados\agendador.log.
$pasta = Split-Path -Parent $MyInvocation.MyCommand.Path
$cfg = @{}
Get-Content (Join-Path $pasta "agendador.txt") | Where-Object { $_ -match "^[A-Z_]+=" } | ForEach-Object {
    $k, $v = $_ -split "=", 2; $cfg[$k] = $v.Trim()
}
$log = Join-Path $pasta "agendador.log"
$projeto = Split-Path -Parent $pasta

# Aviso se alguem religar o WhatsApp Leads neste computador (o certo e so no servidor)
$wlAberto = $false
try { $c = New-Object Net.Sockets.TcpClient; $c.Connect("127.0.0.1", 8000); $wlAberto = $c.Connected; $c.Close() } catch {}
if ($wlAberto) {
    Add-Content -Path $log -Value ("{0:dd/MM HH:mm:ss} ATENCAO: o WhatsApp Leads esta ligado NESTE computador; feche-o (ele roda no servidor)" -f (Get-Date)) -Encoding utf8
}

# Copias de seguranca: 1 vez por dia, depois das 08:00, baixa do servidor as de hoje (Prospeccao e WhatsApp Leads)
# e manda para o Google Drive. Se falhar, tenta de novo so depois de 2 horas.
$backups = Join-Path $pasta "backups"
$baixadaHoje = Join-Path $backups ("baixada_{0:yyyy-MM-dd}.txt" -f (Get-Date))
$tentativa = Join-Path $backups "ultima_tentativa_baixar.txt"
$podeTentar = $true
if (Test-Path $tentativa) { $podeTentar = ((Get-Date) - (Get-Item $tentativa).LastWriteTime).TotalMinutes -ge 120 }
$python = Join-Path $projeto ".venv\Scripts\python.exe"
if ((Get-Date).Hour -ge 8 -and -not (Test-Path $baixadaHoje) -and $podeTentar -and (Test-Path $python)) {
    if (-not (Test-Path $backups)) { New-Item -ItemType Directory -Path $backups | Out-Null }
    Set-Content -Path $tentativa -Value ((Get-Date).ToString("o")) -Encoding utf8
    $p = Start-Process -FilePath $python -ArgumentList "-W", "ignore", "servidor\pc\baixar_copias.py" -WorkingDirectory $projeto `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $backups "baixar_saida.txt") `
        -RedirectStandardError (Join-Path $backups "baixar_erros.txt")
    if ($p.WaitForExit(600000) -and $p.ExitCode -eq 0) {
        Set-Content -Path $baixadaHoje -Value ((Get-Date).ToString("o")) -Encoding utf8
        Get-ChildItem $backups -Filter "baixada_*.txt" | Where-Object { $_.Name -ne (Split-Path -Leaf $baixadaHoje) } | Remove-Item -ErrorAction SilentlyContinue
    }
}

# Reserva do relogio: o servidor chama a cada minuto; esta chamada so trabalha se ele parar (app/relogio.py).
# Economia: pula se chamou ha menos de 50 s; fora do horario comercial, so a cada 5 minutos.
$marca = Join-Path $pasta "ultima_chamada.txt"
$agora = Get-Date
if (Test-Path $marca) {
    $ultima = [datetime]::MinValue
    if ([datetime]::TryParse((Get-Content $marca -Raw).Trim(), [ref]$ultima) -and ($agora - $ultima).TotalSeconds -lt 50) { exit }
}
$minutos = $agora.Hour * 60 + $agora.Minute
$comercial = ($agora.DayOfWeek -ne "Saturday") -and ($agora.DayOfWeek -ne "Sunday") -and ($minutos -ge 450) -and ($minutos -lt 1140)
if (-not $comercial -and ($agora.Minute % 5) -ne 0) { exit }
Set-Content -Path $marca -Value ($agora.ToString("o")) -Encoding utf8
try {
    $r = Invoke-WebRequest -Uri ($cfg["SITE"] + "/api/cron?reserva=1") -Headers @{ Authorization = "Bearer " + $cfg["CRON_SECRET"] } `
        -TimeoutSec 290 -UseBasicParsing
    $linha = "{0:dd/MM HH:mm:ss} {1} {2}" -f (Get-Date), $r.StatusCode, $r.Content
} catch {
    $linha = "{0:dd/MM HH:mm:ss} ERRO {1}" -f (Get-Date), $_.Exception.Message
}
$antigas = @(); if (Test-Path $log) { $antigas = @(Get-Content $log -Tail 1999) }
Set-Content -Path $log -Value ($antigas + $linha) -Encoding utf8
