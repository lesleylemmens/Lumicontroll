$ErrorActionPreference = "Continue"

$NodeIp = "192.168.178.107"
$Port = 6454
$OutFile = Join-Path $PSScriptRoot "artnet_network_test_result.txt"

function Write-Log($Text) {
    $Text | Tee-Object -FilePath $OutFile -Append
}

function Get-NodeJson {
    try {
        return (Invoke-WebRequest -UseBasicParsing -Uri "http://$NodeIp/json" -TimeoutSec 5).Content
    } catch {
        return "ERROR: $($_.Exception.Message)"
    }
}

function New-ArtDmxPacket([int]$Universe, [int]$Seq) {
    $packet = New-Object byte[] 530
    $id = [Text.Encoding]::ASCII.GetBytes("Art-Net")
    [Array]::Copy($id, 0, $packet, 0, $id.Length)
    $packet[7] = 0
    $packet[8] = 0x00
    $packet[9] = 0x50
    $packet[10] = 0
    $packet[11] = 14
    $packet[12] = [byte]($Seq -band 0xff)
    $packet[13] = 0
    $packet[14] = [byte]($Universe -band 0xff)
    $packet[15] = [byte](($Universe -shr 8) -band 0xff)
    $packet[16] = 0x02
    $packet[17] = 0x00
    $packet[18] = 255
    $packet[19] = 255
    $packet[20] = 255
    return $packet
}

Set-Content -Path $OutFile -Value "Art-Net network test $(Get-Date -Format s)"
Write-Log "Running as: $(whoami)"
Write-Log "Admin check:"
cmd /c "net session" *>&1 | Tee-Object -FilePath $OutFile -Append

Write-Log ""
Write-Log "Initial node JSON:"
Write-Log (Get-NodeJson)

Write-Log ""
Write-Log "Route:"
route print $NodeIp | Tee-Object -FilePath $OutFile -Append

Write-Log ""
Write-Log "ARP:"
arp -a $NodeIp | Tee-Object -FilePath $OutFile -Append

Write-Log ""
Write-Log "Preparing PktMon..."
pktmon stop *>&1 | Tee-Object -FilePath $OutFile -Append
pktmon filter remove *>&1 | Tee-Object -FilePath $OutFile -Append
pktmon filter add ArtNetNode -i $NodeIp -t UDP -p $Port *>&1 | Tee-Object -FilePath $OutFile -Append
pktmon filter list *>&1 | Tee-Object -FilePath $OutFile -Append

Write-Log ""
Write-Log "Starting PktMon counters..."
pktmon start --capture --counters-only --comp nics *>&1 | Tee-Object -FilePath $OutFile -Append
Start-Sleep -Milliseconds 500

Write-Log ""
Write-Log "Sending direct unicast ArtDMX to $NodeIp`:6454, universe 1, ch1-3=255..."
$udp = New-Object System.Net.Sockets.UdpClient
$remote = New-Object System.Net.IPEndPoint ([System.Net.IPAddress]::Parse($NodeIp), $Port)
for ($i = 1; $i -le 180; $i++) {
    $packet = New-ArtDmxPacket -Universe 1 -Seq $i
    [void]$udp.Send($packet, $packet.Length, $remote)
    Start-Sleep -Milliseconds 20
}
$udp.Close()
Start-Sleep -Milliseconds 750

Write-Log ""
Write-Log "Node JSON after send:"
Write-Log (Get-NodeJson)

Write-Log ""
Write-Log "PktMon counters:"
pktmon counters *>&1 | Tee-Object -FilePath $OutFile -Append

Write-Log ""
Write-Log "Stopping PktMon and cleaning filters..."
pktmon stop *>&1 | Tee-Object -FilePath $OutFile -Append
pktmon filter remove *>&1 | Tee-Object -FilePath $OutFile -Append

Write-Log ""
Write-Log "Done."
