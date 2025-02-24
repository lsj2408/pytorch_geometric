from torch_geometric.typing import Adj, Size, OptTensor

from torch import Tensor
from torch_sparse import SparseTensor, matmul, set_diag, sum as sparsesum
from torch_geometric.nn.conv import MessagePassing
from torch_geometric.nn.dense.linear import Linear
from torch_geometric.utils import remove_self_loops, add_self_loops, degree


class ClusterGCNConv(MessagePassing):
    r"""The ClusterGCN graph convolutional operator from the
    `"Cluster-GCN: An Efficient Algorithm for Training Deep and Large Graph
    Convolutional Networks" <https://arxiv.org/abs/1905.07953>`_ paper

    .. math::
        \mathbf{X}^{\prime} = \left( \mathbf{\hat{A}} + \lambda \cdot
        \textrm{diag}(\mathbf{\hat{A}}) \right) \mathbf{X} \mathbf{W}_1 +
        \mathbf{X} \mathbf{W}_2

    where :math:`\mathbf{\hat{A}} = {(\mathbf{D} + \mathbf{I})}^{-1}(\mathbf{A}
    + \mathbf{I})`.

    Args:
        in_channels (int): Size of each input sample, or :obj:`-1` to derive
            the size from the first input(s) to the forward method.
        out_channels (int): Size of each output sample.
        diag_lambda: (float, optional): Diagonal enhancement value
            :math:`\lambda`. (default: :obj:`0.`)
        add_self_loops (bool, optional): If set to :obj:`False`, will not add
            self-loops to the input graph. (default: :obj:`True`)
        bias (bool, optional): If set to :obj:`False`, the layer will not learn
            an additive bias. (default: :obj:`True`)
        **kwargs (optional): Additional arguments of
            :class:`torch_geometric.nn.conv.MessagePassing`.
    """
    def __init__(self, in_channels: int, out_channels: int,
                 diag_lambda: float = 0., add_self_loops: bool = True,
                 bias: bool = True, **kwargs):
        kwargs.setdefault('aggr', 'add')
        super().__init__(**kwargs)

        self.in_channels = in_channels
        self.out_channels = out_channels
        self.diag_lambda = diag_lambda
        self.add_self_loops = add_self_loops

        self.lin_out = Linear(in_channels, out_channels, bias=bias,
                              weight_initializer='glorot')
        self.lin_root = Linear(in_channels, out_channels, bias=False,
                               weight_initializer='glorot')

        self.reset_parameters()

    def reset_parameters(self):
        self.lin_out.reset_parameters()
        self.lin_root.reset_parameters()

    def forward(self, x: Tensor, edge_index: Adj, size: Size = None) -> Tensor:
        """"""
        edge_weight: OptTensor = None
        if isinstance(edge_index, Tensor):
            num_nodes = size[1] if size is not None else x.size(self.node_dim)
            if self.add_self_loops:
                edge_index, _ = remove_self_loops(edge_index)
                edge_index, _ = add_self_loops(edge_index, num_nodes=num_nodes)

            row, col = edge_index[0], edge_index[1]
            deg_inv = 1. / degree(col, num_nodes=num_nodes).clamp_(1.)

            edge_weight = deg_inv[col]
            edge_weight[row == col] += self.diag_lambda * deg_inv

        elif isinstance(edge_index, SparseTensor):
            if self.add_self_loops:
                edge_index = set_diag(edge_index)

            col, row, _ = edge_index.coo()  # Transposed.
            deg_inv = 1. / sparsesum(edge_index, dim=1).clamp_(1.)

            edge_weight = deg_inv[col]
            edge_weight[row == col] += self.diag_lambda * deg_inv
            edge_index = edge_index.set_value(edge_weight, layout='coo')

        # propagate_type: (x: Tensor, edge_weight: OptTensor)
        out = self.propagate(edge_index, x=x, edge_weight=edge_weight,
                             size=None)
        out = self.lin_out(out) + self.lin_root(x)

        return out

    def message(self, x_j: Tensor, edge_weight: Tensor) -> Tensor:
        return edge_weight.view(-1, 1) * x_j

    def message_and_aggregate(self, adj_t: SparseTensor, x: Tensor) -> Tensor:
        return matmul(adj_t, x, reduce=self.aggr)

    def __repr__(self):
        return '{}({}, {}, diag_lambda={})'.format(self.__class__.__name__,
                                                   self.in_channels,
                                                   self.out_channels,
                                                   self.diag_lambda)
