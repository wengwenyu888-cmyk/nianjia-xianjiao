$ErrorActionPreference='Continue'
$ws='C:\Users\wengw\Documents\deepseek-harness\default-workspace'
$rb='C:\$Recycle.Bin\S-1-5-21-474016326-4287297538-2606612004-1001'
$agents='C:\Users\wengw\.agents\skills'

# --- all I records ---
$all=@()
Get-ChildItem -LiteralPath $rb -Force -File -Filter '$I*' | ForEach-Object {
  $b=[System.IO.File]::ReadAllBytes($_.FullName)
  if($b.Length -ge 28){
    $sz=[BitConverter]::ToInt64($b,8); $ft=[BitConverter]::ToInt64($b,16); $nl=[BitConverter]::ToInt32($b,24)
    if($nl -gt 0 -and (28+$nl*2) -le $b.Length){
      $nm=[Text.Encoding]::Unicode.GetString($b,28,$nl*2).TrimEnd([char]0)
      $all+=[pscustomobject]@{Orig=$nm;Size=$sz}
    }
  }
}

$qskills = $all | Where-Object { $_.Orig -like '*openclaw-quarantine-20260917\*' -and $_.Orig -match '\\skills\\' -and $_.Size -gt 0 }

# --- R blob index by ext|size ---
$ridx=@{}
Get-ChildItem -LiteralPath $rb -Force -File | Where-Object { $_.Name.StartsWith('$R') } | ForEach-Object {
  $k = $_.Extension.ToLower() + '|' + $_.Length
  if(-not $ridx.ContainsKey($k)){ $ridx[$k]=New-Object System.Collections.ArrayList }
  [void]$ridx[$k].Add($_.FullName)
}

function Get-Sha([string]$p){
  try { return (Get-FileHash -LiteralPath $p -Algorithm SHA256 -ErrorAction Stop).Hash }
  catch { return $null }
}

$rows=@()
foreach($rec in $qskills){
  $orig=$rec.Orig
  # locate the owning skills root
  $m=[regex]::Match($orig,'openclaw-quarantine-20260917\\(?<rest>.+)$')
  if(-not $m.Success){continue}
  $rel=$m.Groups['rest'].Value
  $skill=$null; $sub=$null
  $idx=$rel.IndexOf('\skills\')
  if($idx -lt 0){continue}
  $after=$rel.Substring($idx+8)
  $parts=$after -split '\\'
  if($parts.Count -lt 2){continue}
  $skill=$parts[0]
  $sub=($parts[1..($parts.Count-1)] -join '\')
  $ap=Join-Path (Join-Path $agents $skill) $sub
  if(-not (Test-Path -LiteralPath $ap -PathType Leaf)){ continue }

  $k=[IO.Path]::GetExtension($sub).ToLower()+'|'+$rec.Size
  $blobs=@()
  if($ridx.ContainsKey($k)){ foreach($bb in $ridx[$k]){ $blobs+=[string]$bb } }
  $iSame = @($all | Where-Object { $_.Orig -ne $orig -and $_.Size -eq $rec.Size -and ([IO.Path]::GetExtension($_.Orig).ToLower() -eq [IO.Path]::GetExtension($sub).ToLower()) }).Count

  $verdict='UNRESOLVED'
  if($blobs.Count -eq 0){ $verdict='BLOB-GONE' }
  elseif($blobs.Count -eq 1){
      $rh=Get-Sha $blobs[0]; $ah=Get-Sha $ap
      if($rh -and $ah){ $verdict = if($rh -eq $ah){'SHA256-MATCH'}else{'SHA256-DIFFER'} } else { $verdict='HASH-ERROR' }
  } else {
      $ah=Get-Sha $ap
      $hit=0; foreach($c in $blobs){ $r2=Get-Sha $c; if($r2 -and $r2 -eq $ah){$hit++} }
      $verdict = if($hit -gt 0){'SHA256-MATCH-AMBIG'} else {'NO-MATCH-AMBIG'}
  }
  $rows+=[pscustomobject]@{Skill=$skill;Sub=$sub;Size=$rec.Size;Ext=[IO.Path]::GetExtension($sub).ToLower();Blobs=$blobs.Count;SameExtSizeInI=$iSame;Verdict=$verdict}
}

$rows | Export-Csv (Join-Path $ws 'hash_verify2.csv') -NoTypeInformation -Encoding UTF8
"records considered = $($rows.Count)"
"=== VERDICT SUMMARY ==="
$rows | Group-Object Verdict | Sort-Object Count -Descending | Select-Object Count,Name | Format-Table -AutoSize | Out-String -Width 60
"=== per-skill: MATCH count / total considered, with any DIFFER ==="
$bySkill = $rows | Group-Object Skill | Sort-Object Name
$out = foreach($g in $bySkill){
  $match=@($g.Group | Where-Object {$_.Verdict -like 'SHA256-MATCH*'}).Count
  $differ=@($g.Group | Where-Object {$_.Verdict -eq 'SHA256-DIFFER'}).Count
  $gone=@($g.Group | Where-Object {$_.Verdict -eq 'BLOB-GONE'}).Count
  [pscustomobject]@{Skill=$g.Name;Total=$g.Count;Match=$match;Differ=$differ;BlobGone=$gone;Other=($g.Count-$match-$differ-$gone)}
}
$out | Sort-Object Name | Format-Table -AutoSize | Out-String -Width 120
"TOTALS: considered=$($rows.Count) match=$(@($rows|Where-Object{$_.Verdict -like 'SHA256-MATCH*'}).Count) differ=$(@($rows|Where-Object{$_.Verdict -eq 'SHA256-DIFFER'}).Count) blobGone=$(@($rows|Where-Object{$_.Verdict -eq 'BLOB-GONE'}).Count)"
