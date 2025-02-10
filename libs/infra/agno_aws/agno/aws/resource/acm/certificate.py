from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from typing_extensions import Literal

from agno.aws.api_client import AwsApiClient
from agno.aws.resource.base import AwsResource
from agno.cli.console import print_info, print_subheading
from agno.utils.log import logger


class CertificateSummary(BaseModel):
    CertificateArn: str
    DomainName: Optional[str] = None


class AcmCertificate(AwsResource):
    """
    You can use Amazon Web Services Certificate Manager (ACM) to manage SSL/TLS
    certificates for your Amazon Web Services-based websites and applications.

    Reference:
    - https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/acm.html
    """

    resource_type: Optional[str] = "AcmCertificate"
    service_name: str = "acm"

    # website base domain name, such as example.com
    name: str
    # Fully qualified domain name (FQDN), such as www.example.com,
    # that you want to secure with an ACM certificate.
    #
    # Use an asterisk (*) to create a wildcard certificate that protects several sites in the same domain.
    # For example, *.example.com protects www.example.com, site.example.com, and images.example.com.

    # The first domain name you enter cannot exceed 64 octets, including periods.
    # Each subsequent Subject Alternative Name (SAN), however, can be up to 253 octets in length.

    # If None, defaults to "*.name"
    domain_name: Optional[str] = None
    # The method you want to use if you are requesting a public certificate to validate that you own or control domain.
    # You can validate with DNS or validate with email .
    # We recommend that you use DNS validation.
    validation_method: Literal["EMAIL", "DNS"] = "DNS"
    # Additional FQDNs to be included in the Subject Alternative Name extension of the ACM certificate.
    # For example, add the name www.example.net to a certificate for which the DomainName field is www.example.com
    # if users can reach your site by using either name. The maximum number of domain names that you can add to an
    # ACM certificate is 100. However, the initial quota is 10 domain names. If you need more than 10 names,
    # you must request a quota increase.
    subject_alternative_names: Optional[List[str]] = None
    # Customer chosen string that can be used to distinguish between calls to RequestCertificate .
    # Idempotency tokens time out after one hour. Therefore, if you call RequestCertificate multiple times with
    # the same idempotency token within one hour, ACM recognizes that you are requesting only one certificate
    # and will issue only one. If you change the idempotency token for each call, ACM recognizes that you are
    # requesting multiple certificates.
    idempotency_token: Optional[str] = None
    # The domain name that you want ACM to use to send you emails so that you can validate domain ownership.
    domain_validation_options: Optional[List[dict]] = None
    options: Optional[dict] = None
    certificate_authority_arn: Optional[str] = None
    tags: Optional[List[dict]] = None

    # If True, stores the certificate summary in the file `certificate_summary_file`
    store_cert_summary: bool = False
    # Path for the certificate_summary_file
    certificate_summary_file: Optional[Path] = None

    wait_for_create: bool = False

    def _create(self, aws_client: AwsApiClient) -> bool:
        """Requests an ACM certificate for use with other Amazon Web Services.

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        print_info(f"Creating {self.get_resource_type()}: {self.get_resource_name()}")

        # Step 1: Build ACM configuration
        domain_name = self.domain_name
        if domain_name is None:
            domain_name = self.name
        print_info(f"Requesting AcmCertificate for: {domain_name}")

        # create a dict of args which are not null, otherwise aws type validation fails
        not_null_args: Dict[str, Any] = {}
        if self.subject_alternative_names is not None:
            not_null_args["SubjectAlternativeNames"] = self.subject_alternative_names
            print_info("SANs:")
            for san in self.subject_alternative_names:
                print_info(f"    - {san}")
        if self.idempotency_token is not None:
            not_null_args["IdempotencyToken"] = self.idempotency_token
        if self.domain_validation_options is not None:
            not_null_args["DomainValidationOptions"] = self.domain_validation_options
        if self.options is not None:
            not_null_args["Options"] = self.options
        if self.certificate_authority_arn is not None:
            not_null_args["CertificateAuthorityArn"] = self.certificate_authority_arn
        if self.tags is not None:
            not_null_args["Tags"] = self.tags

        # Step 2: Request AcmCertificate
        service_client = self.get_service_client(aws_client)
        try:
            request_cert_response = service_client.request_certificate(
                DomainName=domain_name,
                ValidationMethod=self.validation_method,
                **not_null_args,
            )
            logger.debug(f"AcmCertificate: {request_cert_response}")

            # Validate AcmCertificate creation
            certificate_arn = request_cert_response.get("CertificateArn", None)
            if certificate_arn is not None:
                print_subheading("---- Please Note: Certificate ARN ----")
                print_info(f"{certificate_arn}")
                print_subheading("--------\n")
                self.active_resource = request_cert_response
                return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be created.")
            logger.error(e)
        return False

    def post_create(self, aws_client: AwsApiClient) -> bool:
        # Wait for AcmCertificate to be validated
        if self.wait_for_create:
            try:
                print_info(f"Waiting for {self.get_resource_type()} to be created.")
                waiter = self.get_service_client(aws_client).get_waiter("certificate_validated")
                certificate_arn = self.get_certificate_arn(aws_client)
                waiter.wait(
                    CertificateArn=certificate_arn,
                    WaiterConfig={
                        "Delay": self.waiter_delay,
                        "MaxAttempts": self.waiter_max_attempts,
                    },
                )
            except Exception as e:
                logger.error("Waiter failed.")
                logger.error(e)

        # Store cert summary if needed
        if self.store_cert_summary:
            if self.certificate_summary_file is None:
                logger.error("certificate_summary_file not provided")
                return False

            try:
                read_cert_summary = self._read(aws_client)
                if read_cert_summary is None:
                    logger.error("certificate_summary not available")
                    return False

                cert_summary = CertificateSummary(**read_cert_summary)
                if not self.certificate_summary_file.exists():
                    self.certificate_summary_file.parent.mkdir(parents=True, exist_ok=True)
                    self.certificate_summary_file.touch(exist_ok=True)
                self.certificate_summary_file.write_text(cert_summary.json(indent=2))
                print_info(f"Certificate Summary stored at: {str(self.certificate_summary_file)}")
            except Exception as e:
                logger.error("Could not writing Certificate Summary to file")
                logger.error(e)

        return True

    def _read(self, aws_client: AwsApiClient) -> Optional[Any]:
        """Returns the Certificate ARN

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        logger.debug(f"Reading {self.get_resource_type()}: {self.get_resource_name()}")

        from botocore.exceptions import ClientError

        service_client = self.get_service_client(aws_client)
        try:
            list_certificate_response = service_client.list_certificates()
            # logger.debug(f"AcmCertificate: {list_certificate_response}")

            current_cert = None
            certificate_summary_list = list_certificate_response.get("CertificateSummaryList", [])
            for cert_summary in certificate_summary_list:
                domain = cert_summary.get("DomainName", None)
                if domain is not None and domain == self.name:
                    current_cert = cert_summary
            # logger.debug(f"current_cert: {current_cert}")
            # logger.debug(f"current_cert type: {type(current_cert)}")

            if current_cert is not None:
                logger.debug(f"AcmCertificate found: {self.name}")
                self.active_resource = current_cert
        except ClientError as ce:
            logger.debug(f"ClientError: {ce}")
        except Exception as e:
            logger.error(f"Error reading {self.get_resource_type()}.")
            logger.error(e)
        return self.active_resource

    def _delete(self, aws_client: AwsApiClient) -> bool:
        """Deletes a certificate and its associated private key.

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        print_info(f"Deleting {self.get_resource_type()}: {self.get_resource_name()}")

        service_client = self.get_service_client(aws_client)
        self.active_resource = None
        try:
            certificate_arn = self.get_certificate_arn(aws_client)
            if certificate_arn is not None:
                delete_cert_response = service_client.delete_certificate(
                    CertificateArn=certificate_arn,
                )
                logger.debug(f"delete_cert_response: {delete_cert_response}")
                print_info(f"AcmCertificate deleted: {self.name}")
            else:
                print_info("AcmCertificate not found")
            return True
        except Exception as e:
            logger.error(e)
        return False

    def get_certificate_arn(self, aws_client: AwsApiClient) -> Optional[str]:
        cert_summary = self._read(aws_client)
        if cert_summary is None:
            return None
        cert_arn = cert_summary.get("CertificateArn", None)
        return cert_arn
