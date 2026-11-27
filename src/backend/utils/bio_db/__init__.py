# -*- coding: utf-8 -*-
"""生物数据库下载、云端同步、状态中心与 Provider 模块包。"""
from .cloud_sync import DEFAULT_NCBI_CLOUD_MIRRORS, NcbiCloudMirror, sync_ncbi_blast_db_from_cloud
from .downloader import (
    CancelSignal,
    DownloadCancelledError,
    DownloadConfig,
    DownloadProgressCallback,
    stream_download_file,
    stream_download_with_mirrors,
)
from .providers import (
    BioDatabase,
    CardDatabase,
    CddPfamDatabase,
    DefenseFinderDatabase,
    FastaProtDatabase,
    Ncbi16SDatabase,
    PhageScopeDatabase,
    PharokkaDatabase,
    PholdDatabase,
    ProgressReporter,
    RdpDatabase,
    SilvaDatabase,
    create_database_provider,
)
from .state_registry import DbUpdateStateRegistry
from .subprocess_runner import (
    build_wsl_script_argv,
    build_wsl_script_command,
    resolve_makeblastdb,
)

__all__ = [
    "BioDatabase",
    "CancelSignal",
    "CardDatabase",
    "CddPfamDatabase",
    "DEFAULT_NCBI_CLOUD_MIRRORS",
    "DbUpdateStateRegistry",
    "DefenseFinderDatabase",
    "DownloadCancelledError",
    "DownloadConfig",
    "DownloadProgressCallback",
    "FastaProtDatabase",
    "Ncbi16SDatabase",
    "NcbiCloudMirror",
    "PhageScopeDatabase",
    "PharokkaDatabase",
    "PholdDatabase",
    "ProgressReporter",
    "RdpDatabase",
    "SilvaDatabase",
    "build_wsl_script_argv",
    "build_wsl_script_command",
    "create_database_provider",
    "resolve_makeblastdb",
    "stream_download_file",
    "stream_download_with_mirrors",
    "sync_ncbi_blast_db_from_cloud",
]
