#!/usr/bin/env python

# flac2mp3.py
# Script to convert a flac dir to mp3 dir
# Option to create a "staged" dir for delivery to exFat/fat32 drives

# imports
import argparse
import os
import subprocess

from collections.abc import Iterable, Sequence
from functools import partial
from itertools import chain
from multiprocessing import Pool
from pathlib import Path

from rich import print
from tqdm import tqdm


def get_file_list(target_dir: os.PathLike, search_exp: Sequence[str]) -> tuple[Path, list[Path]]:
    
    # check target_dir
    target_dir = Path(target_dir)
    if not target_dir.is_dir():
        raise NotADirectoryError(f'target directory {target_dir} is not a directory')

    # check if iterable is single element str, then cast to iterable
    if isinstance(search_exp, str):
        search_exp = [search_exp]   

    # walk the target dir for all matching files and trim base dir
    base_dir_len = len(target_dir.parts)
    file_list = [Path(*f.parts[base_dir_len:]) for f in chain.from_iterable([target_dir.glob(s) for s in search_exp])]
    return (target_dir, file_list)


def get_changelog(sdir: os.PathLike, tdir: os.PathLike, mkdir: bool = False) -> Iterable[Path]:

    # ensure sdir is Path
    sdir = Path(sdir)
    if not sdir.is_dir():
        raise NotADirectoryError(f'target directory {sdir} is not a directory')

    # ensure tdir is Path
    tdir = Path(tdir)
    if not tdir.is_dir():
        if not mkdir:
            raise NotADirectoryError(f'target directory {tdir} is not a directory')

        tdir.mkdir()

    # generate sdir and tdir file sets
    # for sdir, search for .flac or .mp3 files
    sdir_ext = ['.flac', '.mp3']
    # for tdir, only search for .mp3 files
    tdir_ext = ['.mp3']

    # over each of sdir_files and tdir_files, remove the file extension
    # don't worry about generating duplicate file paths
    # set cast will clear them, then we prioritize entry 0 of sdir_ext when recombining
    # if recomb does not result in file, we move down to entry 1, etc.
    sdir_files = {Path(*(f.parts[:-1] + tuple([f.stem]))) for f in get_file_list(target_dir=sdir, search_exp=['**/*' + e for e in sdir_ext])[1]}
    tdir_files = {Path(*(f.parts[:-1] + tuple([f.stem]))) for f in get_file_list(target_dir=tdir, search_exp=['**/*' + e for e in tdir_ext])[1]}
    change_set = sdir_files - tdir_files

    # change set is the set of all files in sdir that are not in tdir, ignoring extensions
    # now, reconstruct the path to each source file with extensions
    sources = []
    for f in change_set:
        for e in sdir_ext:
            test_path = Path(*f.parts[:-1]) / (str(f.parts[-1]) + e)
            if (sdir / test_path).is_file():
                sources.append(test_path)
                break

    return sources


def generate_commands(sources: Iterable[Path], sdir: os.PathLike, tdir: os.PathLike, tsuffix: str = '.mp3', qscale: int = 0) -> Sequence[str]:

    # check that tdir is Path and dir
    tdir = Path(tdir)
    if not tdir.is_dir():
        raise NotADirectoryError(f'target directory {tdir} is not a directory')

    # check that sdir is Path and dir
    sdir = Path(sdir)
    if not sdir.is_dir():
        raise NotADirectoryError(f'target directory {sdir} is not a directory')

    # check that qscale between 0 and 9
    if qscale < 0 or qscale > 9:
        raise ValueError(f'qscale {qscale} out of bounds [0-9], see https://trac.ffmpeg.org/wiki/Encode/MP3 for more info')

    # iterate over each source to create a changelog list of tuples with proper extensions
    changes = [(sdir / f, tdir / Path(str(f)[:-len(f.suffix)] + tsuffix)) for f in sources]

    # convert changes list to a list of commands
    # ffmpeg -i input.flac -ab 320k -map_metadata 0 -id3v2_version 3 output.mp3
    commands = []
    for s, t in changes:
        t.parent.mkdir(parents=True, exist_ok=True)

        # handle special characters in s and t
        source_str = "\"" + str(s).replace(r'$', r'\$') + "\""
        target_str = "\"" + str(t).replace(r'$', r'\$') + "\""

        # check if source is already an mp3, if so just make a copy command
        if s.suffix == tsuffix:
            commands.append(' '.join(['cp', source_str, target_str]))
        else:
            commands.append(' '.join(['ffmpeg', '-i', source_str, '-codec:a', 'libmp3lame', '-qscale:a', str(qscale), '-map_metadata', '0', '-id3v2_version', '3', target_str]))

    return commands


def main(sdir: os.PathLike, tdir: os.PathLike, qscale: int) -> None:

    # interpret sdir and tdir with Path and expand user if possible
    sdir = Path(sdir).expanduser()
    tdir = Path(tdir).expanduser()
    tdir.mkdir(parents=True, exist_ok=True)

    # generate the commands to update tdir
    commands = generate_commands(
        sources=get_changelog(sdir=sdir, tdir=tdir),
        sdir=sdir,
        tdir=tdir,
        tsuffix='.mp3',
        qscale=qscale
    )

    # run commands in multiprocessing pool
    print(f'converting {len(commands)} files from {sdir} to {tdir}')
    exceptions = 0
    with Pool(processes=os.cpu_count()) as pool:
        run_part = partial(subprocess.run, capture_output=True, shell=True)
        for r in tqdm(pool.imap_unordered(run_part, commands), total=len(commands)):
            if r.returncode != 0:
                exceptions += 1
                print(f'command: {r.args}\nreturns: {r.returncode}\nout: {r.stdout.decode()}\nerr: {r.stderr.decode()}')
    print(f'conversion complete with {exceptions} errors')


if __name__ == '__main__':
    # parse arguments for sdir, tdir, mkdir, overwrite
    parser = argparse.ArgumentParser(
        prog='flac2mp3',
        description='Converts a flac dir to mp3 dir',
    )
    parser.add_argument('sdir', type=Path)
    parser.add_argument('tdir', type=Path)
    parser.add_argument('-q', '--qscale', type=int, default=2)
    args = parser.parse_args()

    # pass arguments to main function
    main(
        sdir=args.sdir,
        tdir=args.tdir,
        qscale=args.qscale
    )
