"""Encoders in TensorFlow."""
# pylint: disable=abstract-method
from garage.np.embeddings import Encoder as BaseEncoder
from garage.np.embeddings import StochasticEncoder as BaseStochasticEncoder
from garage.tf.models import Module, StochasticModule


class Encoder(BaseEncoder, Module):
    """Base class for encoders in TensorFlow."""

    def forward_n(self, input_values):
        """Get samples of embedding for the given inputs.

        Args:
            input_values (numpy.ndarray): Tensors to encode.

        Returns:
            numpy.ndarray: Embeddings sampled from embedding distribution.
            dict: Embedding distribution information.

        Note:
            It returns an embedding and a dict, with keys
            - mean (list[numpy.ndarray]): Means of the distribution.
            - log_std (list[numpy.ndarray]): Log standard deviations of the
                distribution.

        """

    def clone(self, name):
        """Return a clone of the encoder.

        It only copies the configuration of the primitive,
        not the parameters.

        Args:
            name (str): Name of the newly created encoder. It has to be
                different from source encoder if cloned under the same
                computational graph.

        Returns:
            garage.tf.embeddings.encoder.Encoder: Newly cloned encoder.

        """


class StochasticEncoder(BaseStochasticEncoder, StochasticModule):
    """Base class for stochastic encoders in TensorFlow."""

    def build(self, embedding_input, name=None):
        """Build encoder.

        After buil, self.distribution is a Gaussian distribution conitioned
        on embedding_input.

        Args:
          embedding_input (tf.Tensor) : Embedding input.
          name (str): Name of the model, which is also the name scope.

        """