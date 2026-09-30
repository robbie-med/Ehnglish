# Montreal Forced Aligner with the US English ARPA models baked in, plus a tiny HTTP shim.
FROM mmcauliffe/montreal-forced-aligner:latest
USER root
RUN mfa model download acoustic english_us_arpa && mfa model download dictionary english_us_arpa
COPY server/mfa_service/app.py /srv/app.py
ENV PORT=8700
EXPOSE 8700
CMD ["python", "/srv/app.py"]
