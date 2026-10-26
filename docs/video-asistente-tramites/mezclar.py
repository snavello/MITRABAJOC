"""Mezcla: narración en sus tiempos + música agachada debajo de la voz + normalización."""
import json, subprocess, sys, os
R = os.path.dirname(os.path.abspath(__file__))
tl = json.load(open(os.path.join(R, 'timeline2.json')))
voces = tl['voces']; dur = tl['duracion']
ins = ['-i', os.path.join(R, 'musica', tl['musica']['archivo'])]
fil = []
for i, v in enumerate(voces):
    ins += ['-i', os.path.join(R, 'voz', v['archivo'])]
    fil.append(f"[{i+1}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={int(v['t']*1000)}|{int(v['t']*1000)}[v{i}]")
vmix = ''.join(f'[v{i}]' for i in range(len(voces))) + f"amix=inputs={len(voces)}:normalize=0,volume=1.0,apad=whole_dur={dur+1}[voz]"
fil.append(vmix)
m = tl['musica']
fil.append(f"[0:a]atrim=start={m.get('desde',0)}:end={m.get('desde',0)+dur+1},asetpts=PTS-STARTPTS,aresample=48000,afade=t=in:st=0:d=0.6,afade=t=out:st={dur-1.6}:d=1.5,volume={m.get('volumen',0.9)}[mus0]")
fil.append("[voz]asplit=2[vozA][vozB]")
fil.append("[mus0][vozB]sidechaincompress=threshold=0.02:ratio=6:attack=40:release=600:makeup=1[mus]")
fil.append("[mus][vozA]amix=inputs=2:normalize=0,loudnorm=I=-15:TP=-1.2:LRA=11[out]")
cmd = ['ffmpeg', '-v', 'error', '-y'] + ins + ['-filter_complex', ';'.join(fil), '-map', '[out]', '-t', str(dur), '-ar', '48000', os.path.join(R, 'mezcla.wav')]
print(' '.join(cmd)[:300]); subprocess.run(cmd, check=True); print('mezcla ok')
