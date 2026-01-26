# Elastic BLAST 云服务器功能使用说明

## 简介

本程序集成了 Elastic BLAST 云服务器功能，允许您利用 Amazon Web Services (AWS) 或 Google Cloud Platform (GCP) 的计算资源进行大规模 BLAST 搜索。
相比本地 BLAST，云服务器具有更高的计算能力和可扩展性，适用于处理大型数据库和海量序列数据。

## 前提条件

在使用云服务器功能之前，请确保您已满足以下前提条件：

1.  **有效的云服务账号**:
    *   **AWS**: 拥有 AWS 账号，并已创建 IAM 用户，配置了访问密钥 (Access Key ID 和 Secret Access Key)。
    *   **GCP**: 拥有 GCP 账号，并已创建项目，启用 Compute Engine API 和 Cloud Storage API，配置了服务账号密钥。

2.  **安装云服务 CLI 工具**:
    *   **AWS**: 安装 AWS CLI 工具 (`aws`) 并配置默认区域和凭证。
    *   **GCP**: 安装 Google Cloud SDK (`gcloud`) 并配置默认项目和凭证。

3.  **配置存储桶 (Bucket)**:
    *   **AWS**: 创建 S3 存储桶，用于存储 Elastic BLAST 的结果文件。
    *   **GCP**: 创建 Cloud Storage 存储桶，用于存储 Elastic BLAST 的结果文件。

4.  **Elastic BLAST 设置**:
    *   确保您已在程序的“高级参数配置”中正确配置了 Elastic BLAST 相关的参数。

## 配置 Elastic BLAST

1.  **打开高级参数配置**:
    *   在主窗口的菜单栏中，依次选择“设置” -> “设置”。
    *   这将打开“高级参数配置”对话框。

2.  **选择 Elastic BLAST 标签页**:
    *   在“高级参数配置”对话框中，点击“Elastic BLAST (云端)”标签页。

3.  **启用 Elastic BLAST**:
    *   勾选“启用 Elastic BLAST (云端运行)”复选框。

4.  **配置云服务提供商**:
    *   在“云服务提供商”下拉框中，选择您要使用的云平台 (AWS 或 GCP)。

5.  **配置区域 (Region)**:
    *   在“区域 (Region)”文本框中，输入云服务器所在的区域。
    *   **AWS**: 例如 `us-east-1`。
    *   **GCP**: 例如 `us-east4`。

6.  **配置结果存储桶 (Results Bucket)**:
    *   在“结果存储桶 (Bucket)”文本框中，输入用于存储 Elastic BLAST 结果的存储桶 URI。
    *   **AWS**: 例如 `s3://your-bucket-name/results`。
    *   **GCP**: 例如 `gs://your-bucket-name/results`。

7.  **配置机器类型 (Machine Type) (可选)**:
    *   在“机器类型 (Machine Type)”文本框中，输入您要使用的云服务器实例类型。
    *   如果留空，程序将自动选择合适的实例类型。

8.  **配置节点数量 (Num Nodes) (可选)**:
    *   在“节点数量 (Num Nodes)”微调框中，输入您要使用的计算节点数量。
    *   节点越多，计算速度越快，但费用也越高。
    *   如果留空，程序将使用默认的节点数量 (1)。

9.  **使用 Spot/Preemptible 实例 (可选)**:
    *   勾选“使用 Spot/Preemptible 实例 (更便宜)”复选框，以使用 AWS Spot 实例或 GCP Preemptible 实例。
    *   这些实例的价格通常较低，但可能会被中断。

10. **保存设置**:
    *   点击“确定保存”按钮，保存您的 Elastic BLAST 配置。

## 运行 Elastic BLAST

1.  **选择序列文件**:
    *   在主窗口的“文件选择”区域，选择您要进行 BLAST 搜索的序列文件。

2.  **配置其他参数**:
    *   在“参数配置”区域，配置 BLAST 程序的其他参数，例如数据库、E-value 等。

3.  **启动 BLAST 搜索**:
    *   点击“控制面板”区域的“开始处理”按钮。

4.  **监控任务状态**:
    *   程序将在状态栏中显示 Elastic BLAST 任务的状态。
    *   您还可以在“云资源管理器”对话框中查看更详细的任务状态。

## 云资源管理器

云资源管理器允许您管理和清理 Elastic BLAST 在云端创建的资源。

1.  **打开云资源管理器**:
    *   在主窗口的菜单栏中，依次选择“设置” -> “云资源管理器”。

2.  **配置目标配置**:
    *   云资源管理器会自动加载您在“高级参数配置”中设置的 Elastic BLAST 参数。
    *   您也可以手动修改这些参数，以管理其他存储桶或区域的资源。

3.  **检查状态**:
    *   点击“检查状态”按钮，查询指定存储桶关联的 Elastic BLAST 集群状态。
    *   程序将在日志输出区域显示集群状态、任务统计和详细信息。

4.  **删除/清理集群**:
    *   点击“删除/清理集群”按钮，发送删除命令，清理云端残留的集群资源。
    *   **警告**: 此操作不可逆，将终止所有正在运行的任务并释放计算资源。

## 常见问题

1.  **Elastic BLAST 任务失败**:
    *   检查您的云服务账号是否已正确配置，并且具有足够的权限。
    *   检查您的存储桶 URI 是否正确，并且存储桶存在。
    *   检查您的网络连接是否正常。
    *   查看程序日志输出，获取详细的错误信息。

2.  **云端资源未被清理**:
    *   使用云资源管理器手动清理残留的集群资源。
    *   确保您已配置了正确的存储桶和区域。

## 更多信息

有关 Elastic BLAST 的更多信息，请参考以下资源：

*   **Elastic BLAST 官方文档**: [https://ncbi.github.io/blast_plus_docs/doc/elastic-blast.html](https://ncbi.github.io/blast_plus_docs/doc/elastic-blast.html)

## 联系方式

如果您在使用过程中遇到任何问题，请联系我们：

*   **邮箱**: your-email@example.com
